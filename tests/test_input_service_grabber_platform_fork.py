"""Platform-fork tests for InputService._start_key_grabber."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService


def _make_service():
    wm = MagicMock()
    wm.get_active_window.return_value = ""
    return InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [],
        get_movement_modes=lambda: [],
        get_event_queue_func=lambda: None,
    )


class TestPlatformFork:
    def test_linux_uses_movement_key_grabber(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        from utils import x11_movement_grabber as xmg
        monkeypatch.setattr(xmg, "xlib_available", lambda: True)

        # Avoid touching CC detection
        from services import wine_runtimes
        monkeypatch.setattr(wine_runtimes, "discover_cc_installs", lambda: [MagicMock()])

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(xmg, "MovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        assert svc._key_grabber is stub
        stub.prepare.assert_called_once()

    def test_windows_uses_win32_movement_key_grabber(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from utils import win32_movement_grabber as wmg

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        assert svc._key_grabber is stub
        stub.prepare.assert_called_once()

    def test_windows_skips_cc_install_detection(self, monkeypatch):
        """The Windows path must NOT call discover_cc_installs; the grabber
        is cheap enough to install unconditionally and the discovery code
        is Linux-CC-prefix-shaped."""
        monkeypatch.setattr(sys, "platform", "win32")
        from utils import win32_movement_grabber as wmg
        from services import wine_runtimes

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub)

        called = MagicMock()
        monkeypatch.setattr(wine_runtimes, "discover_cc_installs", called)

        svc = _make_service()
        svc._start_key_grabber()
        called.assert_not_called()

    def test_windows_prepare_failure_clears_grabber(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from utils import win32_movement_grabber as wmg

        stub = MagicMock()
        stub.prepare.return_value = False
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        assert svc._key_grabber is None

    def test_idempotent_when_already_initialized(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        svc = _make_service()
        sentinel = MagicMock()
        svc._key_grabber = sentinel
        svc._start_key_grabber()
        assert svc._key_grabber is sentinel
