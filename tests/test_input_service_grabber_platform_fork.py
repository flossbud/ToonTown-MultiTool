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


class TestWin32CcFocusSafety:
    """Win32 CC-focus must NEVER pass route_all to install_grabs.

    TTR strict separation is Linux/X11-only in v1; the Win32 grabber does
    not accept a route_all kwarg.  Passing it would break CC movement on
    Windows.  Even if a future refactor accidentally gates the wrong branch,
    this test catches it before it reaches users."""

    def test_cc_focus_win32_does_not_pass_route_all(self, monkeypatch):
        """Focus a CC window on win32 platform.  install_grabs must be called
        (CC movement still needs the grabber), but 'route_all' must NOT appear
        in the call's keyword arguments."""
        monkeypatch.setattr(sys, "platform", "win32")

        from utils import win32_movement_grabber as wmg
        from utils import game_registry as gr
        from services import wine_runtimes

        stub_grabber = MagicMock()
        stub_grabber.prepare.return_value = True
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub_grabber)

        fake_registry = MagicMock()
        fake_registry.get_game_for_window.return_value = "cc"
        monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_registry)

        svc = _make_service()
        svc.window_manager.get_active_window.return_value = "cc_win"
        svc.window_manager.get_window_ids.return_value = ["cc_win"]

        # Wire a fake keymap so _canonical_set_for_toon_index resolves.
        fake_km = MagicMock()
        fake_km.get_key_for_action.return_value = "w"  # set 0, forward -> wasd
        svc.keymap_manager = fake_km
        svc.get_keymap_assignments = lambda: [0]
        svc.get_enabled_toons = lambda: [True]

        svc._start_key_grabber()

        assert stub_grabber.install_grabs.called, (
            "install_grabs must be called for a CC window focus on win32"
        )
        for call in stub_grabber.install_grabs.call_args_list:
            _, call_kwargs = call
            assert "route_all" not in call_kwargs, (
                f"CC focus on win32 must NOT pass route_all to install_grabs; "
                f"got kwargs={call_kwargs}"
            )
