"""X11GlobalHotkeys unit tests against a fake Display - no real X."""
import pytest

pytest.importorskip("Xlib")

from utils.hotkey_chords import parse_chord
from services.global_hotkeys import (
    X11GlobalHotkeys, _compile_bindings, _LOCK_COMBOS,
)


class _FakeRoot:
    def __init__(self):
        self.grabs = []      # (keycode, modmask, keyboard_mode)
        self.ungrabs = []
        self.onerrors = []
        self.fail_keycodes = set()   # grab_key raises for these keycodes
    def grab_key(self, keycode, modmask, owner_events, ptr_mode, kbd_mode,
                 onerror=None):
        if keycode in self.fail_keycodes:
            raise RuntimeError(f"grab refused for keycode {keycode}")
        self.grabs.append((keycode, modmask, kbd_mode))
        self.onerrors.append(onerror)
    def ungrab_key(self, keycode, modmask):
        self.ungrabs.append((keycode, modmask))


class _FakeDisplay:
    def __init__(self, keycodes=None):
        self._keycodes = keycodes or {"h": 43, "F5": 71, "1": 10}
        self.synced = 0
        self.allow_calls = []        # allow_events modes, in call order
        self._keymap = [0] * 32      # query_keymap physical state
    def keysym_to_keycode(self, keysym):
        # the compiler passes the RESOLVED keysym; fake maps via a side table
        return self._by_keysym.get(keysym, 0)
    def sync(self):
        self.synced += 1
    def allow_events(self, mode, time, onerror=None):
        self.allow_calls.append(mode)
    def query_keymap(self):
        return list(self._keymap)
    def set_key_down(self, keycode):
        self._keymap[keycode >> 3] |= (1 << (keycode & 7))
    def set_key_up(self, keycode):
        self._keymap[keycode >> 3] &= ~(1 << (keycode & 7))


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
    assert table[(43, X.ControlMask | X.Mod1Mask)] == ("overlay.toggle_cards",
                                                       None)
    assert table[(71, 0)] == ("app.refresh", None)


def test_compile_reports_unresolvable_keysym():
    d = _fake_display()
    table, failures = _compile_bindings(d, {"x.y": "ctrl+KP_Banana"})
    assert table == {} and "x.y" in failures


def test_compile_two_key_chord_makes_two_partner_entries():
    # A two-key chord contributes one entry per member (resolved in sorted
    # order: frozenset iteration order is unstable), each pointing at the
    # OTHER member's keycode. The old "not supported yet" refusal is gone.
    from Xlib import X
    d = _fake_display()
    table, failures = _compile_bindings(d, {"a.pair": "ctrl+1+h"})
    assert failures == {}
    assert table == {
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    }


def test_compile_pair_member_collision_never_half_inserts():
    from Xlib import X
    d = _fake_display()
    # single first: the pair's 'h' member collides -> pair fails whole,
    # its '1' member must NOT be armed either.
    table, failures = _compile_bindings(
        d, {"a.single": "ctrl+h", "a.pair": "ctrl+1+h"})
    assert failures == {"a.pair": "duplicate of a.single"}
    assert table == {(43, X.ControlMask): ("a.single", None)}
    # pair first: the later single collides and fails; the pair stays whole.
    table, failures = _compile_bindings(
        d, {"a.pair": "ctrl+1+h", "a.single": "ctrl+h"})
    assert failures == {"a.single": "duplicate of a.pair"}
    assert table == {
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    }


def _bare_provider():
    prov = X11GlobalHotkeys.__new__(X11GlobalHotkeys)   # no real X connect
    prov._display, prov._root = _fake_display(), _FakeRoot()
    prov._grabbed = {}
    prov._grab_sync = set()
    prov._table = {}
    prov._failures = {}
    prov._down = set()
    return prov


def test_grab_diffing_grabs_and_ungrabs():
    prov = _bare_provider()
    prov._apply_compiled({(43, 12): ("a.b", None)})
    assert len(prov._root.grabs) == len(_LOCK_COMBOS)    # one chord, all lock variants
    prov._apply_compiled({(71, 0): ("c.d", None)})
    assert len(prov._root.ungrabs) == len(_LOCK_COMBOS)  # old chord ungrabbed
    assert prov._table == {(71, 0): ("c.d", None)}


def test_compile_reports_duplicate_chord_collision():
    from Xlib import X
    d = _fake_display()
    table, failures = _compile_bindings(
        d, {"a.first": "ctrl+alt+h", "a.second": "ctrl+alt+h"})
    assert table == {(43, X.ControlMask | X.Mod1Mask): ("a.first", None)}
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
    prov._apply_compiled({(43, 12): ("a.b", None)})
    assert prov.failures() == {"a.b": "in use by another application"}
    assert (43, 12) not in prov._grabbed
    # every grab request carried the error trap
    assert len(prov._root.grabs) == len(_LOCK_COMBOS)
    assert all(h is not None for h in prov._root.onerrors)
    # all-or-nothing cleanup: every lock-combo grab released
    assert sorted(prov._root.ungrabs) == sorted(
        (43, 12 | lock) for lock in _LOCK_COMBOS)


def test_apply_pair_entries_grab_sync_singles_async():
    from Xlib import X
    prov = _bare_provider()
    prov._apply_compiled({
        (71, 0): ("app.refresh", None),
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    })
    modes = {}
    for keycode, _mask, kbd_mode in prov._root.grabs:
        modes.setdefault(keycode, set()).add(kbd_mode)
    assert modes[71] == {X.GrabModeAsync}
    assert modes[10] == {X.GrabModeSync}
    assert modes[43] == {X.GrabModeSync}
    assert prov._grab_sync == {(10, X.ControlMask), (43, X.ControlMask)}
    assert prov.failures() == {}


def test_apply_regrabs_key_whose_mode_changed():
    # (keycode, mask) rebinding from a single to a pair member must NOT keep
    # its stale async grab (a pair member needs Sync so the partner check can
    # replay; a leftover async grab would silently EAT the key instead).
    from Xlib import X
    prov = _bare_provider()
    prov._apply_compiled({(43, X.ControlMask): ("a.single", None)})
    prov._apply_compiled({
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    })
    # ungrabbed once (all lock combos), then re-grabbed sync
    assert len([u for u in prov._root.ungrabs if u[0] == 43]) == len(_LOCK_COMBOS)
    sync_grabs = [g for g in prov._root.grabs
                  if g[0] == 43 and g[2] == X.GrabModeSync]
    assert len(sync_grabs) == len(_LOCK_COMBOS)
    assert (43, X.ControlMask) in prov._grab_sync
    assert prov._grabbed[(43, X.ControlMask)] == "a.pair"


def test_pair_member_grab_failure_cascades_to_both():
    # All-or-nothing across the PAIR: one member failing must release the
    # other member too (never a half-armed chord), one failure per action.
    from Xlib import X
    prov = _bare_provider()
    prov._root.fail_keycodes = {43}
    prov._apply_compiled({
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    })
    assert list(prov.failures()) == ["a.pair"]
    assert prov._grabbed == {} and prov._grab_sync == set()
    assert {kc for kc, _ in prov._root.ungrabs} == {10, 43}


def test_pair_member_grab_failure_skips_later_member():
    # Failing member FIRST in iteration order: the later member must be
    # skipped entirely (no grab requests issued for it).
    from Xlib import X
    prov = _bare_provider()
    prov._root.fail_keycodes = {10}
    prov._apply_compiled({
        (10, X.ControlMask): ("a.pair", 43),
        (43, X.ControlMask): ("a.pair", 10),
    })
    assert list(prov.failures()) == ["a.pair"]
    assert prov._grabbed == {}
    assert not [g for g in prov._root.grabs if g[0] == 43]


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


def test_stamp_lists_pair_action_once():
    prov = _bare_provider()
    prov._grabbed = {(10, 4): "a.pair", (43, 4): "a.pair"}
    prov._failures = {}
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        prov._print_stamp()
    assert buf.getvalue().strip() == "[GlobalHotkeys] armed: a.pair"


# ---- _handle_event: sync-frozen pair presses ---------------------------

class _Ev:
    def __init__(self, detail, etype, state=0):
        self.detail = detail
        self.type = etype
        self.state = state


def _pair_table():
    from Xlib import X
    return {(10, X.ControlMask): ("a.pair", 43),
            (43, X.ControlMask): ("a.pair", 10)}


def _handler_provider(table, repeat_ok=frozenset(), keymap_down=()):
    prov = X11GlobalHotkeys(repeat_ok_ids=repeat_ok)
    prov._close_wake_pipe()          # never started: don't leak the pipe fds
    prov._display, prov._root = _fake_display(), _FakeRoot()
    prov._table = dict(table)
    prov._grab_sync = {k for k, v in table.items() if v[1] is not None}
    for kc in keymap_down:
        prov._display.set_key_down(kc)
    return prov


def test_partner_down_consumes_and_fires_repeat_gated():
    from Xlib import X
    prov = _handler_provider(_pair_table(), keymap_down=(10, 43))
    fired = []
    prov.action_triggered.connect(fired.append)
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    assert prov._display.allow_calls == [X.AsyncKeyboard]
    assert fired == ["a.pair"]
    # auto-repeat press while held: thawed again (harmless no-op), NOT re-fired
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    assert fired == ["a.pair"]
    assert prov._display.allow_calls == [X.AsyncKeyboard, X.AsyncKeyboard]


def test_partner_down_repeat_ok_fires_each_press():
    from Xlib import X
    prov = _handler_provider(_pair_table(),
                             repeat_ok=frozenset({"a.pair"}),
                             keymap_down=(10, 43))
    fired = []
    prov.action_triggered.connect(fired.append)
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    assert fired == ["a.pair", "a.pair"]


def test_partner_up_replays_and_never_fires():
    from Xlib import X
    prov = _handler_provider(_pair_table(), keymap_down=(43,))  # partner 10 UP
    fired = []
    prov.action_triggered.connect(fired.append)
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    assert prov._display.allow_calls == [X.ReplayKeyboard]
    assert fired == []
    assert prov._down == set()


def test_partner_check_raising_still_thaws_via_finally():
    # FREEZE-SAFETY INVARIANT: a raising partner check must still reach
    # allow_events (fail-safe ReplayKeyboard), never crash, never fire.
    from Xlib import X
    prov = _handler_provider(_pair_table(), keymap_down=(10, 43))
    fired = []
    prov.action_triggered.connect(fired.append)

    def _boom(_kc):
        raise RuntimeError("keymap exploded")
    prov._key_physically_down = _boom
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))   # must not raise
    assert prov._display.allow_calls == [X.ReplayKeyboard]
    assert fired == []


def test_pair_release_no_allow_events_and_down_cleared():
    # No AllowEvents on KeyRelease: after AsyncKeyboard the active grab runs
    # async (the release arrives unfrozen); after ReplayKeyboard the grab was
    # released (the release never reaches us). _down clears per physical state.
    from Xlib import X
    prov = _handler_provider(_pair_table(), keymap_down=(10, 43))
    prov._handle_event(_Ev(43, X.KeyPress, X.ControlMask))
    assert (43, X.ControlMask) in prov._down
    prov._display.allow_calls.clear()
    # auto-repeat release (key still physically down): keeps _down
    prov._handle_event(_Ev(43, X.KeyRelease, X.ControlMask))
    assert (43, X.ControlMask) in prov._down
    # real release
    prov._display.set_key_up(43)
    prov._handle_event(_Ev(43, X.KeyRelease, X.ControlMask))
    assert (43, X.ControlMask) not in prov._down
    assert prov._display.allow_calls == []      # releases never AllowEvents


def test_unmatched_keypress_thaws_defensively():
    # Rebuild-race guard: a KeyPress sync-frozen under a grab that a rebind
    # just removed would otherwise never reach an allow_events (system-wide
    # keyboard freeze). AllowEvents is a no-op when nothing is frozen, so
    # the handler thaws defensively on every unmatched press.
    from Xlib import X
    prov = _handler_provider({})                # table emptied by a rebind
    prov._handle_event(_Ev(99, X.KeyPress, 0))
    assert prov._display.allow_calls == [X.ReplayKeyboard]
    prov._handle_event(_Ev(99, X.KeyRelease, 0))
    assert prov._display.allow_calls == [X.ReplayKeyboard]   # presses only


def test_single_entry_fires_and_thaws_defensively():
    # Matched singles keep today's fire semantics; the AsyncKeyboard thaw is
    # a no-op on a normal async-grab press and covers the pair->single
    # rebind race (a frozen press whose entry just lost its partner).
    from Xlib import X
    prov = _handler_provider({(71, 0): ("app.refresh", None)})
    fired = []
    prov.action_triggered.connect(fired.append)
    prov._handle_event(_Ev(71, X.KeyPress, 0))
    assert fired == ["app.refresh"]
    assert prov._display.allow_calls == [X.AsyncKeyboard]
