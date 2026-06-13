"""Tests for the darwin dispatch branches in InputService.

These tests pin sys.platform to "darwin" and verify:
- _ttr_strict_supported includes darwin
- _delivery_backend_ready requires a connected backend on darwin (no xdotool)
- _send_via_backend never calls _safe_run (xdotool) on darwin
"""
import importlib
import sys

import pytest

isvc = importlib.import_module("services.input_service")


def _bare():
    s = isvc.InputService.__new__(isvc.InputService)
    s._xlib = None
    s._xlib_backend_failed = False
    s._xlib_unavailable_logged = False
    s.settings_manager = None
    s.logging_enabled = False
    return s


def test_ttr_strict_supported_includes_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _bare()._ttr_strict_supported() is True


def test_delivery_ready_darwin_requires_connected_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    s = _bare()
    # no backend, not failed -> NOT ready (no xdotool on darwin)
    assert s._delivery_backend_ready() is False
    # connected backend -> ready
    s._xlib = object()
    assert s._delivery_backend_ready() is True
    # failed backend -> not ready
    s._xlib = None
    s._xlib_backend_failed = True
    assert s._delivery_backend_ready() is False


class _StubWindowManager:
    """Minimal stub for the window_manager attribute."""
    def get_active_window(self):
        return "11"

    def assign_windows(self):
        pass


def test_send_via_backend_darwin_no_backend_drops_never_xdotool(monkeypatch):
    """darwin with no backend drops the event; _safe_run (xdotool) is NEVER reached."""
    monkeypatch.setattr(sys, "platform", "darwin")
    s = _bare()
    s._xlib = None
    s._xlib_backend_failed = False
    s.window_manager = _StubWindowManager()

    def _boom(*args, **kwargs):
        raise AssertionError("_safe_run (xdotool) must never be called on darwin")

    s._safe_run = _boom
    # Must not raise — drops with notice, returns cleanly
    s._send_via_backend("keydown", "11", "w")
    # Confirm the drop was logged (flag flipped)
    assert s._xlib_unavailable_logged is True


def test_send_via_backend_darwin_connected_backend_routes_correctly(monkeypatch):
    """darwin with a connected backend routes through the backend; xdotool never runs."""
    monkeypatch.setattr(sys, "platform", "darwin")
    s = _bare()
    s.window_manager = _StubWindowManager()

    calls = []

    class _FakeBackend:
        def send_keydown(self, win_id, keysym):
            calls.append(("keydown", win_id, keysym))
            return True

        def send_keyup(self, win_id, keysym):
            calls.append(("keyup", win_id, keysym))
            return True

        def send_key(self, win_id, keysym, modifiers):
            calls.append(("key", win_id, keysym, modifiers))
            return True

    s._xlib = _FakeBackend()
    s._xlib_backend_failed = False

    def _boom(*args, **kwargs):
        raise AssertionError("_safe_run (xdotool) must never be called on darwin")

    s._safe_run = _boom

    s._send_via_backend("keydown", "11", "w")

    assert calls == [("keydown", "11", "w")], f"Expected backend call, got: {calls}"
