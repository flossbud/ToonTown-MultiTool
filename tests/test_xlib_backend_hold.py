"""Backend-level hold-shape tests for XlibBackend.

Mocks Xlib.display.Display so the test runs without an X server.
Verifies that send_keydown -> send_keyup produces two distinct
send_event calls with X.KeyPress and X.KeyRelease event types,
preserving the contract that hold-mirror tests at the InputService
layer assume.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

import sys
from unittest.mock import MagicMock


def _make_backend_with_mocked_display(monkeypatch):
    """Construct an XlibBackend whose _display is a MagicMock that
    captures send_event calls. Returns (backend, fake_window, fake_X)."""
    fake_X = MagicMock()
    fake_X.KeyPress = 2
    fake_X.KeyRelease = 3
    fake_X.CurrentTime = 0
    fake_X.NONE = 0
    fake_xevent = MagicMock()

    class _FakeWin:
        def __init__(self):
            self.events = []
        def send_event(self, ev, propagate=True):
            self.events.append(ev)
        def __int__(self):
            return 12345

    fake_window = _FakeWin()
    fake_protocol = MagicMock()
    fake_protocol.event = fake_xevent
    fake_Xlib = MagicMock(X=fake_X)
    fake_Xlib.protocol = fake_protocol
    monkeypatch.setitem(sys.modules, "Xlib", fake_Xlib)
    monkeypatch.setitem(sys.modules, "Xlib.display", MagicMock())
    monkeypatch.setitem(sys.modules, "Xlib.X", fake_X)
    monkeypatch.setitem(sys.modules, "Xlib.protocol", fake_protocol)
    monkeypatch.setitem(sys.modules, "Xlib.protocol.event", fake_xevent)
    monkeypatch.setitem(sys.modules, "Xlib.error", MagicMock(BadWindow=ValueError))

    if "utils.xlib_backend" in sys.modules:
        del sys.modules["utils.xlib_backend"]
    from utils.xlib_backend import XlibBackend

    backend = XlibBackend()
    fake_display = MagicMock()
    fake_display.keysym_to_keycode.return_value = 65
    fake_display.create_resource_object.return_value = fake_window
    fake_display.screen.return_value.root = MagicMock()
    backend._display = fake_display
    return backend, fake_window, fake_X


def test_send_keydown_then_send_keyup_emits_two_distinct_events(monkeypatch):
    backend, window, fake_X = _make_backend_with_mocked_display(monkeypatch)
    backend.send_keydown("12345", "Delete")
    backend.send_keyup("12345", "Delete")
    assert len(window.events) == 2, (
        f"expected 2 send_event calls (KeyPress + KeyRelease), got "
        f"{len(window.events)}: {window.events}"
    )


def test_send_keydown_uses_keypress_event_type(monkeypatch):
    backend, window, fake_X = _make_backend_with_mocked_display(monkeypatch)
    backend.send_keydown("12345", "space")
    assert len(window.events) == 1
    fake_xevent = sys.modules["Xlib.protocol.event"]
    assert fake_xevent.KeyPress.called, (
        "send_keydown must construct a KeyPress event"
    )
    assert not fake_xevent.KeyRelease.called, (
        "send_keydown must NOT construct a KeyRelease event"
    )


def test_send_keyup_uses_keyrelease_event_type(monkeypatch):
    backend, window, fake_X = _make_backend_with_mocked_display(monkeypatch)
    backend.send_keyup("12345", "space")
    assert len(window.events) == 1
    fake_xevent = sys.modules["Xlib.protocol.event"]
    assert fake_xevent.KeyRelease.called, (
        "send_keyup must construct a KeyRelease event"
    )
    assert not fake_xevent.KeyPress.called, (
        "send_keyup must NOT construct a KeyPress event"
    )
