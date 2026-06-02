"""Auto-repeat artifact guard: a buffered keyup must NOT be flushed as a real
release when the key is still physically held.

Root cause this guards against: with two keys held, only the most-recently
pressed key auto-repeats; releasing the OTHER key ends that repeat with a final
UNPAIRED KeyRelease. The time-based dedup would promote that artifact to a real
keyup and stop a still-held toon. The fix validates the flush against
XQueryKeymap (tri-state) and drops releases for keys still physically down.
"""

import queue
import time
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService


# ── XlibBackend.key_physically_down: tri-state ──────────────────────────────

def test_xlib_backend_key_physically_down_tristate(monkeypatch):
    from utils import xlib_backend as xb
    b = xb.XlibBackend()

    # No display -> unknown (None)
    assert b.key_physically_down("w") is None

    # Fake display: 'w' maps to keycode 25; query_keymap reports kc 25 down.
    disp = MagicMock()
    disp.keysym_to_keycodes.side_effect = lambda ks: [(25, 0)]
    disp.keysym_to_keycode.side_effect = lambda ks: 25
    km = [0] * 32
    km[25 >> 3] = 1 << (25 & 7)          # mark kc 25 as down
    disp.query_keymap.return_value = km
    b._display = disp
    assert b.key_physically_down("w") is True      # bit set -> held

    km2 = [0] * 32                                   # nothing down
    disp.query_keymap.return_value = km2
    assert b.key_physically_down("w") is False     # bit clear -> up

    # Query failure -> unknown (None), never a false positive/negative
    disp.query_keymap.side_effect = RuntimeError("boom")
    assert b.key_physically_down("w") is None


# ── InputService._key_still_physically_down: only True on positive down ──────

def _bare_service():
    return InputService(
        window_manager=MagicMock(),
        get_enabled_toons=lambda: [True],
        get_movement_modes=lambda: ["both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0],
        keymap_manager=MagicMock(),
    )


def test_helper_true_only_on_positive_down():
    s = _bare_service()
    s._resolve_keysym = lambda k: k

    s._xlib = None                                   # no backend
    assert s._key_still_physically_down("w") is False

    s._xlib = MagicMock(); s._xlib.key_physically_down = lambda ks: True
    assert s._key_still_physically_down("w") is True

    s._xlib.key_physically_down = lambda ks: False
    assert s._key_still_physically_down("w") is False

    s._xlib.key_physically_down = lambda ks: None    # unknown
    assert s._key_still_physically_down("w") is False

    s._xlib.key_physically_down = lambda ks: (_ for _ in ()).throw(RuntimeError())
    assert s._key_still_physically_down("w") is False


# ── Loop-level: artifact dropped vs real release dispatched ─────────────────

class _FakeKeymap:
    _set = {"forward": "w", "reverse": "s", "left": "a", "right": "d"}
    def get_default(self, game): return dict(self._set)
    def get_action_in_set(self, game, set_idx, key):
        return next((a for a, k in self._set.items() if k == key), None)
    def get_key_for_action(self, game, set_idx, action): return self._set.get(action)
    def get_all_keys(self): return frozenset({"w", "a", "s", "d"})


class _FakeWM:
    def __init__(self): self._ids = ["100", "200"]
    def get_active_window(self): return "100"
    def get_window_ids(self): return list(self._ids)
    def assign_windows(self): pass


def _loop_service(monkeypatch, phys_down):
    sent = []
    reg = MagicMock(); reg.get_game_for_window.side_effect = lambda wid: "ttr"
    monkeypatch.setattr("utils.game_registry.GameRegistry.instance", lambda: reg)
    monkeypatch.setattr(
        "services.input_service.InputService._start_key_grabber", lambda self: None)
    eq = queue.Queue()
    # input_backend must resolve to "xlib" so _apply_backend_setting keeps the
    # injected backend stub (otherwise it disconnects it and self._xlib -> None).
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: "xlib" if key == "input_backend" else default
    s = InputService(
        window_manager=_FakeWM(),
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: eq,
        settings_manager=sm,
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=_FakeKeymap(),
    )
    s._send_via_backend = lambda action, win, keysym, mods=None: sent.append((action, win, keysym))
    s._resolve_keysym = lambda k: k
    # Inject a backend stub whose physical-state answer we control. Set BEFORE
    # start() so _apply_backend_setting (use_xlib=True) keeps it.
    s._xlib = MagicMock(); s._xlib.key_physically_down = lambda ks: phys_down
    return s, eq, sent


def test_buffered_keyup_dropped_when_still_physically_down(monkeypatch):
    """keyup for a key XQueryKeymap reports as still held = auto-repeat artifact
    -> no keyup is ever sent to the toon (it keeps moving)."""
    s, eq, sent = _loop_service(monkeypatch, phys_down=True)
    eq.put(("keydown", "a"))
    eq.put(("keyup", "a"))               # artifact: 'a' still physically down
    s.start()
    time.sleep(0.1)
    # Snapshot WHILE running (before shutdown's release_all_keys drains the
    # still-held key): the artifact keyup must not have been forwarded in-loop.
    downs = [x for x in sent if x[0] == "keydown" and x[2] == "a"]
    ups = [x for x in sent if x[0] == "keyup" and x[2] == "a"]
    s.shutdown()
    assert downs, "keydown should have been forwarded"
    assert ups == [], "artifact keyup must be dropped while key is still held"


def test_buffered_keyup_dispatched_when_physically_up(monkeypatch):
    """keyup for a key XQueryKeymap reports as up = genuine release -> forwarded."""
    s, eq, sent = _loop_service(monkeypatch, phys_down=False)
    eq.put(("keydown", "a"))
    eq.put(("keyup", "a"))               # genuine: 'a' is up
    s.start()
    time.sleep(0.1)
    ups = [x for x in sent if x[0] == "keyup" and x[2] == "a"]
    s.shutdown()
    assert ups, "a genuine release must be forwarded in-loop"
