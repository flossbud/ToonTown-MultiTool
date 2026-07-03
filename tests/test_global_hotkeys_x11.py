"""X11GlobalHotkeys unit tests against a fake Display - no real X."""
import pytest

pytest.importorskip("Xlib")

from utils.hotkey_chords import parse_chord
from services.global_hotkeys import (
    X11GlobalHotkeys, _compile_bindings, _LOCK_COMBOS,
)


class _FakeRoot:
    def __init__(self):
        self.grabs = []      # (keycode, modmask)
        self.ungrabs = []
        self.onerrors = []
    def grab_key(self, keycode, modmask, owner_events, ptr_mode, kbd_mode,
                 onerror=None):
        self.grabs.append((keycode, modmask))
        self.onerrors.append(onerror)
    def ungrab_key(self, keycode, modmask):
        self.ungrabs.append((keycode, modmask))


class _FakeDisplay:
    def __init__(self, keycodes=None):
        self._keycodes = keycodes or {"h": 43, "F5": 71, "1": 10}
        self.synced = 0
    def keysym_to_keycode(self, keysym):
        # the compiler passes the RESOLVED keysym; fake maps via a side table
        return self._by_keysym.get(keysym, 0)
    def sync(self):
        self.synced += 1


def _fake_display():
    from Xlib import XK
    d = _FakeDisplay()
    d._by_keysym = {
        XK.string_to_keysym("h"): 43,
        XK.string_to_keysym("F5"): 71,
        XK.string_to_keysym("1"): 10,
    }
    return d


def test_lock_combo_set_is_lock_only():
    # 0, Lock, Mod2, Mod5 and their ORs = 8 distinct masks, NO user modifiers.
    from Xlib import X
    assert 0 in _LOCK_COMBOS and len(_LOCK_COMBOS) == 8
    assert not any(m & (X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod4Mask)
                   for m in _LOCK_COMBOS)


def test_compile_bindings_resolves_keycode_and_mask():
    from Xlib import X
    d = _fake_display()
    table, failures = _compile_bindings(
        d, {"overlay.toggle_cards": "ctrl+alt+h", "app.refresh": "F5"})
    assert failures == {}
    assert table[(43, X.ControlMask | X.Mod1Mask)] == "overlay.toggle_cards"
    assert table[(71, 0)] == "app.refresh"


def test_compile_reports_unresolvable_keysym():
    d = _fake_display()
    table, failures = _compile_bindings(d, {"x.y": "ctrl+KP_Banana"})
    assert table == {} and "x.y" in failures


def test_compile_defers_multikey_chords_to_failures():
    # Passive per-chord grabs cannot express a two-key hold; a multi-key
    # binding must land in failures with a legible reason and never grab.
    d = _fake_display()
    table, failures = _compile_bindings(d, {"a.b": "ctrl+1+h"})
    assert table == {}
    assert failures["a.b"] == "multi-key chords not yet armed (Task 11)"


def _bare_provider():
    prov = X11GlobalHotkeys.__new__(X11GlobalHotkeys)   # no real X connect
    prov._display, prov._root = _fake_display(), _FakeRoot()
    prov._grabbed = {}
    prov._table = {}
    prov._failures = {}
    prov._down = set()
    return prov


def test_grab_diffing_grabs_and_ungrabs():
    prov = _bare_provider()
    prov._apply_compiled({(43, 12): "a.b"})
    assert len(prov._root.grabs) == len(_LOCK_COMBOS)    # one chord, all lock variants
    prov._apply_compiled({(71, 0): "c.d"})
    assert len(prov._root.ungrabs) == len(_LOCK_COMBOS)  # old chord ungrabbed
    assert prov._table == {(71, 0): "c.d"}


def test_compile_reports_duplicate_chord_collision():
    from Xlib import X
    d = _fake_display()
    table, failures = _compile_bindings(
        d, {"a.first": "ctrl+alt+h", "a.second": "ctrl+alt+h"})
    assert table == {(43, X.ControlMask | X.Mod1Mask): "a.first"}
    assert failures["a.second"] == "duplicate of a.first"


def test_grab_refusal_records_failure_and_releases_all(monkeypatch):
    # A real-server grab refusal arrives as an ASYNC X error (never a raise),
    # trapped by the per-request CatchError handler. Simulate BadAccess.
    from Xlib import error as xerror

    class _FakeCatch:
        def __init__(self, *errors):
            pass
        def get_error(self):
            return xerror.BadAccess.__new__(xerror.BadAccess)

    monkeypatch.setattr("services.global_hotkeys.xerror.CatchError", _FakeCatch)
    prov = _bare_provider()
    prov._apply_compiled({(43, 12): "a.b"})
    assert prov.failures() == {"a.b": "in use by another application"}
    assert (43, 12) not in prov._grabbed
    # every grab request carried the error trap
    assert len(prov._root.grabs) == len(_LOCK_COMBOS)
    assert all(h is not None for h in prov._root.onerrors)
    # all-or-nothing cleanup: every lock-combo grab released
    assert sorted(prov._root.ungrabs) == sorted(
        (43, 12 | lock) for lock in _LOCK_COMBOS)


def test_stamp_reports_actual_grabs_and_every_failure(capsys):
    # The stamp derives from _grabbed (real server-side grabs), never the
    # compiled table, so a grab-time refusal can't print as armed.
    prov = _bare_provider()
    prov._grabbed = {(71, 0): "c.d"}
    prov._failures = {"a.b": "in use by another application"}
    prov._print_stamp()
    assert capsys.readouterr().out.strip() == \
        "[GlobalHotkeys] armed: c.d; unavailable: ['a.b']"
    # fully-armed: no unavailable suffix
    prov._failures = {}
    prov._print_stamp()
    assert capsys.readouterr().out.strip() == "[GlobalHotkeys] armed: c.d"
