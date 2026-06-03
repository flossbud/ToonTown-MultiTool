"""Auto-repeat dedup in InputService.run.

X11 auto-repeat is delivered by pynput as separate keyup+keydown pairs
at the same X timestamp. Without dedup at the run-loop level, each pair
becomes an up/down call to the wine bridge, and CC sees taps instead
of a held press.

These tests drive the run loop via a real thread. The fixture patches
_send_via_backend to capture bridge calls, _start_key_grabber to a
no-op (no CC install needed), and GameRegistry so the window layout
resolves cleanly.
"""

import queue
import time
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService


class _FakeKeymap:
    def __init__(self):
        self._set = {
            "forward": "w", "reverse": "s", "left": "a", "right": "d",
            "jump": "space",
        }

    def get_default(self, game):
        return dict(self._set)

    def get_action_in_set(self, game, set_idx, key):
        for action, k in self._set.items():
            if k == key:
                return action
        return None

    def get_key_for_action(self, game, set_idx, action):
        return self._set.get(action)

    def get_all_keys(self):
        return frozenset({"w", "a", "s", "d", "Up", "Down", "Left", "Right", "space"})

    def get_keys_for_game(self, game):
        # Game-agnostic stub: the foreground-scoped classifier asks per-game,
        # but this fake models a single movement set for all games.
        return self.get_all_keys()


class _FakeWindowManager:
    def __init__(self, focused, ids):
        self._focused = focused
        self._ids = list(ids)

    def get_active_window(self):
        return self._focused

    def get_window_ids(self):
        return list(self._ids)

    def assign_windows(self):
        pass


@pytest.fixture
def svc(monkeypatch):
    sent = []

    fake_registry = MagicMock()
    fake_registry.get_game_for_window.side_effect = lambda wid: "cc"
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    # Suppress the CC-install discovery so _start_key_grabber exits early
    monkeypatch.setattr(
        "services.input_service.InputService._start_key_grabber",
        lambda self: None,
    )

    wm = _FakeWindowManager(focused="100", ids=["100", "200"])
    eq: queue.Queue = queue.Queue()

    km = _FakeKeymap()

    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: eq,
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=km,
    )
    # Capture all bridge sends without real xdotool/wine
    s._send_via_backend = lambda action, win, keysym, mods=None: sent.append(
        (action, win, keysym)
    )
    # Passthrough keysym resolution
    s._resolve_keysym = lambda k: k

    return s, eq, sent


def test_autorepeat_keyup_then_keydown_is_deduped(svc):
    """A keyup immediately followed by a keydown for the same key is
    X11 auto-repeat. The dedup must collapse it to a single sustained
    keydown for the background toon - exactly one bridge keydown, no
    interim keyup - then the final keyup when the user really releases."""
    s, eq, sent = svc

    # Initial real press + 3 auto-repeat ticks (keyup+keydown pairs)
    eq.put(("keydown", "w"))
    eq.put(("keyup", "w"))
    eq.put(("keydown", "w"))
    eq.put(("keyup", "w"))
    eq.put(("keydown", "w"))
    eq.put(("keyup", "w"))
    eq.put(("keydown", "w"))
    # Final keyup (real release) is pushed after a sleep so it falls
    # outside the auto-repeat window of the preceding keydown.

    s.start()
    time.sleep(0.05)   # let the run loop drain the first batch + dedup
    eq.put(("keyup", "w"))
    time.sleep(0.05)   # let the run loop process and flush the final keyup
    s.stop(wait=True)

    bridge_calls_for_bg = [c for c in sent if c[1] == "200"]
    keydown_calls = [c for c in bridge_calls_for_bg if c[0] == "keydown"]
    keyup_calls   = [c for c in bridge_calls_for_bg if c[0] == "keyup"]
    assert len(keydown_calls) == 1, (
        f"expected 1 keydown for bg toon, got {keydown_calls}"
    )
    assert len(keyup_calls) == 1, (
        f"expected 1 keyup for bg toon, got {keyup_calls}"
    )


def test_real_release_without_followup_keydown_is_flushed(svc):
    """A keyup with no matching keydown within the dedup window must be
    delivered to the background toon (not silently dropped)."""
    s, eq, sent = svc

    eq.put(("keydown", "w"))
    s.start()
    time.sleep(0.05)
    # Push the real release well past the AUTO_REPEAT_DEDUP_WINDOW
    eq.put(("keyup", "w"))
    time.sleep(0.05)
    s.stop(wait=True)

    bridge_calls_for_bg = [c for c in sent if c[1] == "200"]
    assert ("keydown", "200", "w") in bridge_calls_for_bg, (
        f"expected bridge keydown for bg toon, got {bridge_calls_for_bg}"
    )
    assert ("keyup", "200", "w") in bridge_calls_for_bg, (
        f"expected bridge keyup for bg toon, got {bridge_calls_for_bg}"
    )


def test_different_keys_do_not_dedupe_each_other(svc):
    """A keyup for W followed by a keydown for A is NOT auto-repeat
    (different keys). Both must be delivered to the background toon."""
    s, eq, sent = svc

    eq.put(("keydown", "w"))
    eq.put(("keyup", "w"))
    eq.put(("keydown", "a"))
    s.start()
    time.sleep(0.10)
    eq.put(("keyup", "a"))
    time.sleep(0.05)
    s.stop(wait=True)

    bridge_calls_for_bg = [c for c in sent if c[1] == "200"]
    assert any(c[0] == "keydown" and c[2] == "w" for c in bridge_calls_for_bg), (
        f"expected keydown w for bg toon, got {bridge_calls_for_bg}"
    )
    assert any(c[0] == "keyup" and c[2] == "w" for c in bridge_calls_for_bg), (
        f"expected keyup w for bg toon, got {bridge_calls_for_bg}"
    )
    assert any(c[0] == "keydown" and c[2] == "a" for c in bridge_calls_for_bg), (
        f"expected keydown a for bg toon, got {bridge_calls_for_bg}"
    )
    assert any(c[0] == "keyup" and c[2] == "a" for c in bridge_calls_for_bg), (
        f"expected keyup a for bg toon, got {bridge_calls_for_bg}"
    )
