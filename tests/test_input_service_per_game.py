"""Unit tests for per-game input service routing.

These tests construct InputService with stub dependencies so the run loop
isn't started. They exercise the resolution and routing helpers directly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_service(monkeypatch, tmp_path, active_wid="100", windows=None):
    """Construct an InputService bound to a stub WindowManager and stub registry."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.keymap_manager import KeymapManager
    from services.input_service import InputService

    km = KeymapManager()
    windows = windows or []

    wm = SimpleNamespace(
        get_active_window=lambda: active_wid,
        get_window_ids=lambda: windows,
        assign_windows=lambda: None,
    )

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(windows),
        get_movement_modes=lambda: ["WASD"] * len(windows),
        get_event_queue_func=lambda: None,
        keymap_manager=km,
        get_keymap_assignments=lambda: [0] * len(windows),
    )
    return svc, km


class TestForegroundGame:
    def test_focus_on_ttr_window_updates_state(self, monkeypatch, tmp_path):
        from utils.game_registry import GameRegistry
        svc, _ = _make_service(monkeypatch, tmp_path, active_wid="ttr-1",
                                windows=["ttr-1"])
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: "ttr" if wid == "ttr-1" else None)
        assert svc._foreground_game() == "ttr"

    def test_focus_on_cc_window_updates_state(self, monkeypatch, tmp_path):
        from utils.game_registry import GameRegistry
        svc, _ = _make_service(monkeypatch, tmp_path, active_wid="cc-1",
                                windows=["cc-1"])
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: "cc" if wid == "cc-1" else None)
        assert svc._foreground_game() == "cc"

    def test_ttmt_focus_preserves_last_known(self, monkeypatch, tmp_path):
        from utils.game_registry import GameRegistry
        svc, _ = _make_service(monkeypatch, tmp_path, active_wid="ttr-1",
                                windows=["ttr-1"])
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: "ttr" if wid == "ttr-1" else None)
        assert svc._foreground_game() == "ttr"
        # Now focus shifts to TTMT (unknown wid)
        svc.window_manager.get_active_window = lambda: "ttmt-window"
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: None)
        assert svc._foreground_game() == "ttr"  # preserved


class TestResolveLogicalAction:
    def test_resolves_via_foreground_default(self, monkeypatch, tmp_path):
        from utils.game_registry import GameRegistry
        svc, _ = _make_service(monkeypatch, tmp_path, active_wid="ttr-1",
                                windows=["ttr-1"])
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: "ttr")
        assert svc._resolve_logical_action("w") == "forward"
        assert svc._resolve_logical_action("space") == "jump"
        assert svc._resolve_logical_action("nonexistent") is None

    def test_resolves_cc_sprint(self, monkeypatch, tmp_path):
        from utils.game_registry import GameRegistry
        svc, _ = _make_service(monkeypatch, tmp_path, active_wid="cc-1",
                                windows=["cc-1"])
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                            lambda wid: "cc")
        assert svc._resolve_logical_action("Shift_L") == "sprint"
        assert svc._resolve_logical_action("w") == "forward"
