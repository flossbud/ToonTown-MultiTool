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


class TestSendLogicalActionKm:
    def _setup_with_two_toons(self, monkeypatch, tmp_path,
                              toon0_game="ttr", toon1_game="cc", fg_game="ttr"):
        from utils.game_registry import GameRegistry
        svc, km = _make_service(
            monkeypatch, tmp_path,
            active_wid="fg-window",
            windows=["bg-0", "bg-1"],
        )
        def _game_for(wid):
            if wid == "fg-window":
                return fg_game
            if wid == "bg-0":
                return toon0_game
            if wid == "bg-1":
                return toon1_game
            return None
        monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window", _game_for)
        sent: list = []
        svc._send_via_backend = lambda action, win, keysym, modifiers=None: \
            sent.append((action, win, keysym, modifiers))
        return svc, km, sent

    def test_press_w_with_ttr_fg_forwards_to_both_games(self, monkeypatch, tmp_path):
        svc, km, sent = self._setup_with_two_toons(monkeypatch, tmp_path,
                                                   toon0_game="ttr", toon1_game="cc",
                                                   fg_game="ttr")
        enabled = [True, True]
        svc._send_logical_action_km("keydown", "w", enabled, [0, 0])
        sent_to = {(s[0], s[1], s[2]) for s in sent}
        assert ("keydown", "bg-0", "w") in sent_to  # TTR Default forward=w
        assert ("keydown", "bg-1", "w") in sent_to  # CC Default forward=w

    def test_press_sprint_with_cc_fg_skips_ttr_toon(self, monkeypatch, tmp_path):
        svc, km, sent = self._setup_with_two_toons(monkeypatch, tmp_path,
                                                   toon0_game="ttr", toon1_game="cc",
                                                   fg_game="cc")
        enabled = [True, True]
        svc._send_logical_action_km("keydown", "Shift_L", enabled, [0, 0])
        sent_wids = {s[1] for s in sent}
        assert "bg-0" not in sent_wids  # TTR doesn't support sprint
        assert "bg-1" in sent_wids       # CC does

    def test_press_unknown_key_no_send(self, monkeypatch, tmp_path):
        svc, km, sent = self._setup_with_two_toons(monkeypatch, tmp_path,
                                                   fg_game="ttr")
        svc._send_logical_action_km("keydown", "j", [True, True], [0, 0])
        assert sent == []

    def test_press_w_with_ttr_fg_translates_for_bg_alt_set(self, monkeypatch, tmp_path):
        svc, km, sent = self._setup_with_two_toons(monkeypatch, tmp_path,
                                                   toon0_game="ttr", toon1_game="ttr",
                                                   fg_game="ttr")
        km.add_set("ttr", name="Arrows")
        km.update_set_key("ttr", 1, "forward", "Up")
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
        sent_payload = {(s[1], s[2]) for s in sent}
        assert ("bg-0", "w") in sent_payload
        assert ("bg-1", "Up") in sent_payload

    def test_chat_active_suppresses_movement(self, monkeypatch, tmp_path):
        svc, km, sent = self._setup_with_two_toons(monkeypatch, tmp_path,
                                                   fg_game="ttr")
        svc.global_chat_active = True
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 0])
        assert sent == []
