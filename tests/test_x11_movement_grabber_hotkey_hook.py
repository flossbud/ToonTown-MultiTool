"""While the persistent route_all XGrabKeyboard is held it PREEMPTS the hotkey
provider's passive grabs, so the router must recognize bound chords itself (via
set_hotkey_lookup) and hand them to the dispatcher instead of routing them.
Everything else stays suppress-only (no on_key / on_passthrough calls)."""
from unittest.mock import MagicMock

import pytest

pytest.importorskip("Xlib")

from utils.x11_movement_grabber import MovementKeyGrabber
from Xlib import X


class _Ev:
    def __init__(self, detail, etype=X.KeyPress, state=0):
        self.detail = detail
        self.type = etype
        self.time = 0
        self.state = state


def _grabber():
    g = MovementKeyGrabber.__new__(MovementKeyGrabber)
    g._on_key = MagicMock()
    g._on_passthrough = MagicMock()
    g._keycode_to_name = {
        25: ("grabbed", "w"),          # movement keysym
        36: ("passthrough", "Return"),
    }
    g._current_canonical = "wasd"
    g._route_all = True
    g._hotkey_lookup = None
    g._hotkey_dispatch_cb = None
    g._hotkey_repeat_ok_ids = frozenset()
    g._hotkey_keys_down = set()
    return g


def test_bound_chord_keypress_is_dispatched_not_routed():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "app.refresh" if keycode == 71 else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(71, state=0))      # bare F5
    assert dispatched == ["app.refresh"]
    g._on_key.assert_not_called()                    # never routed
    g._on_passthrough.assert_not_called()


def test_keyrelease_of_bound_keycode_is_not_dispatched():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "app.refresh" if keycode == 71 else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(71, etype=X.KeyRelease))
    assert dispatched == []                          # KeyPress only
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_unbound_key_proceeds_with_normal_routing():
    # route_all's "normal routing" is suppress-only: the event is dropped here
    # (delivery is the pynput feed's job) -- assert no dispatch and no callbacks.
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(lambda keycode, state, is_down: None, dispatched.append)
    g._handle_event_route_all(_Ev(25))               # movement key, unbound
    g._handle_event_route_all(_Ev(36))               # passthrough key, unbound
    assert dispatched == []
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_raising_lookup_is_treated_as_none():
    def _boom(keycode, state, is_down):
        raise RuntimeError("lookup exploded")

    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(_boom, dispatched.append)
    g._handle_event_route_all(_Ev(71))               # must not raise
    assert dispatched == []
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_no_lookup_wired_is_a_pure_noop():
    g = _grabber()                                   # lookup stays None
    g._handle_event_route_all(_Ev(71))
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_autorepeat_press_dispatches_once():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "app.refresh" if keycode == 71 else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(71))
    g._handle_event_route_all(_Ev(71))               # X auto-repeat press
    assert dispatched == ["app.refresh"]
    g._on_key.assert_not_called()                    # still consumed, never routed


def test_repeat_ok_action_redispatches_on_autorepeat():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "overlay.scale_up" if keycode == 86 else None,
        dispatched.append,
        repeat_ok_ids=frozenset({"overlay.scale_up"}),
    )
    g._handle_event_route_all(_Ev(86))
    g._handle_event_route_all(_Ev(86))
    assert dispatched == ["overlay.scale_up", "overlay.scale_up"]


def test_release_clears_and_repress_fires_again():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "app.refresh" if keycode == 71 else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(71))
    # Physical release: _key_physically_down fails closed on the bare fixture
    # (no display) -> treated as physically up -> tracking cleared.
    g._handle_event_route_all(_Ev(71, etype=X.KeyRelease))
    g._handle_event_route_all(_Ev(71))               # fresh physical press
    assert dispatched == ["app.refresh", "app.refresh"]


def test_partner_entry_dispatches_only_while_partner_held():
    # The 3rd lookup arg is the grabber's own _key_physically_down; a
    # partner-gated (two-key chord) lookup dispatches only while the OTHER
    # member is physically held.
    g = _grabber()
    km = [0] * 32
    km[44 >> 3] |= (1 << (44 & 7))                   # partner keycode 44 held
    g._display = MagicMock()
    g._display.query_keymap.return_value = km
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down:
            "a.pair" if keycode == 43 and is_down(44) else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(43))
    assert dispatched == ["a.pair"]
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_partner_up_member_press_falls_through_to_routing():
    # Partner physically up -> the lookup misses and the member press keeps
    # route_all's normal suppress-only handling (no dispatch, no callbacks;
    # delivery stays the pynput feed's job).
    g = _grabber()
    g._display = MagicMock()
    g._display.query_keymap.return_value = [0] * 32  # nothing held
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down:
            "a.pair" if keycode == 43 and is_down(44) else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(43))
    assert dispatched == []
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_autorepeat_release_does_not_clear_tracking():
    # X auto-repeat is Release+Press with the key STILL physically down; the
    # query_keymap guard must keep the keycode tracked so the paired press is
    # treated as a repeat (single dispatch overall).
    g = _grabber()
    km = [0] * 32
    km[71 >> 3] |= (1 << (71 & 7))                   # keycode 71 held
    g._display = MagicMock()
    g._display.query_keymap.return_value = km
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state, is_down: "app.refresh" if keycode == 71 else None,
        dispatched.append,
    )
    g._handle_event_route_all(_Ev(71))
    g._handle_event_route_all(_Ev(71, etype=X.KeyRelease))   # auto-repeat release
    g._handle_event_route_all(_Ev(71))                        # auto-repeat press
    assert dispatched == ["app.refresh"]
