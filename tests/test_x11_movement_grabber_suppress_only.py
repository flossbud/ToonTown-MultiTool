"""In route_all mode the grabber is suppress-only: it never calls on_passthrough
(delivery moved to the reliable pynput path). The legacy (route_all=False) path
still calls on_passthrough."""
from unittest.mock import MagicMock

from utils.x11_movement_grabber import MovementKeyGrabber
from Xlib import X


class _Ev:
    def __init__(self, detail, etype=X.KeyPress):
        self.detail = detail
        self.type = etype
        self.time = 0


def _grabber():
    g = MovementKeyGrabber.__new__(MovementKeyGrabber)
    g._on_passthrough = MagicMock()
    g._keycode_to_name = {
        25: ("grabbed", "w"),          # movement keysym
        36: ("passthrough", "Return"),
    }
    g._current_canonical = "wasd"
    g._hotkey_lookup = None            # no hotkey hook wired in these tests
    g._hotkey_dispatch_cb = None
    return g


def test_route_all_does_not_call_on_passthrough_for_passthrough_key():
    g = _grabber()
    g._handle_event_route_all(_Ev(36))         # Return press
    g._on_passthrough.assert_not_called()


def test_route_all_does_not_call_on_passthrough_for_grabbed_key():
    g = _grabber()
    g._handle_event_route_all(_Ev(25))         # w press (movement)
    g._on_passthrough.assert_not_called()
