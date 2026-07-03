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
    return g


def test_bound_chord_keypress_is_dispatched_not_routed():
    g = _grabber()
    dispatched = []
    g.set_hotkey_lookup(
        lambda keycode, state: "app.refresh" if keycode == 71 else None,
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
        lambda keycode, state: "app.refresh" if keycode == 71 else None,
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
    g.set_hotkey_lookup(lambda keycode, state: None, dispatched.append)
    g._handle_event_route_all(_Ev(25))               # movement key, unbound
    g._handle_event_route_all(_Ev(36))               # passthrough key, unbound
    assert dispatched == []
    g._on_key.assert_not_called()
    g._on_passthrough.assert_not_called()


def test_raising_lookup_is_treated_as_none():
    def _boom(keycode, state):
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
