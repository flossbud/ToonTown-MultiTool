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

    def test_darwin_uses_macos_movement_key_grabber(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils import macos_movement_grabber as mmg

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(mmg, "MacOSMovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        assert svc._key_grabber is stub
        stub.prepare.assert_called_once()

    def test_darwin_prepare_failure_clears_grabber(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils import macos_movement_grabber as mmg

        stub = MagicMock()
        stub.prepare.return_value = False
        monkeypatch.setattr(mmg, "MacOSMovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        assert svc._key_grabber is None

    def test_darwin_wires_callbacks(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils import macos_movement_grabber as mmg

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(mmg, "MacOSMovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        _, kwargs = stub.prepare.call_args
        assert kwargs.get("on_grabs_changed") == svc._on_grabs_changed
        assert kwargs.get("should_consume") == svc._should_consume_grabbed_key

    def test_idempotent_when_already_initialized(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        svc = _make_service()
        sentinel = MagicMock()
        svc._key_grabber = sentinel
        svc._start_key_grabber()
        assert svc._key_grabber is sentinel

    def test_windows_wires_on_grabs_changed(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from utils import win32_movement_grabber as wmg

        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub)

        svc = _make_service()
        svc._start_key_grabber()
        _, kwargs = stub.prepare.call_args
        assert kwargs.get("on_grabs_changed") == svc._on_grabs_changed


class TestWin32CcFocusSafety:
    """Win32 CC-focus must NEVER pass route_all to install_grabs.

    route_all=True is for TTR strict separation only (grab BOTH keysets). CC
    needs opposite-keyset-only suppression, so its focus-install path must omit
    route_all (which defaults False). Passing it for a CC focus would over-grab
    and break CC movement on Windows.  Even if a future refactor accidentally
    gates the wrong branch, this test catches it before it reaches users."""

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


class TestGrabberCreatedCallback:
    """grabber_created_callback must fire AFTER _key_grabber is assigned and
    BEFORE the seed focus call -- otherwise a service start with a game already
    focused can arm route_all before main wires the hotkey interop (every
    hotkey dead until the next focus change)."""

    def _stubbed_service(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from utils import win32_movement_grabber as wmg
        stub = MagicMock()
        stub.prepare.return_value = True
        monkeypatch.setattr(wmg, "Win32MovementKeyGrabber", lambda: stub)
        return _make_service(), stub

    def test_callback_fires_after_assignment_before_seed(self, monkeypatch):
        svc, stub = self._stubbed_service(monkeypatch)
        order = []
        svc.grabber_created_callback = (
            lambda: order.append(("callback", svc._key_grabber is stub)))
        monkeypatch.setattr(
            svc, "_on_active_window_changed_for_grabber",
            lambda win_id: order.append(("seed", win_id)))
        svc._start_key_grabber()
        assert ("callback", True) in order            # grabber already assigned
        assert ("seed", "") in order                  # seed still ran
        assert order.index(("callback", True)) < order.index(("seed", ""))

    def test_raising_callback_does_not_break_startup(self, monkeypatch):
        svc, stub = self._stubbed_service(monkeypatch)

        def _boom():
            raise RuntimeError("wiring exploded")

        svc.grabber_created_callback = _boom
        seed = MagicMock()
        monkeypatch.setattr(svc, "_on_active_window_changed_for_grabber", seed)
        svc._start_key_grabber()                      # must not raise
        assert svc._key_grabber is stub
        seed.assert_called_once_with("")
