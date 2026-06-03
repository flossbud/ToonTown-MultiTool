"""Focused-toon passthrough delivery: the helpers that send non-movement keys
to the focused TTR window via the reliable pynput path and pair their release
to the exact window/keysym they were sent to."""
import queue
from unittest.mock import MagicMock

from services.input_service import InputService


class _WM:
    def __init__(self, active="100", ids=("100", "200")):
        self._active = active
        self._ids = list(ids)
    def get_active_window(self):
        return self._active
    def get_window_ids(self):
        return list(self._ids)
    def assign_windows(self):
        pass


def _make_svc(monkeypatch, active="100", game="ttr"):
    reg = MagicMock()
    reg.get_game_for_window.side_effect = lambda wid: game
    monkeypatch.setattr("utils.game_registry.GameRegistry.instance", lambda: reg)
    svc = InputService(
        window_manager=_WM(active=active),
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    svc._send_via_backend = MagicMock()
    return svc


def test_send_passthrough_gated_off_when_strict_inactive(monkeypatch):
    svc = _make_svc(monkeypatch)
    svc._strict_ttr_active = lambda: False
    svc._send_passthrough_to_focused("Return")
    svc._send_via_backend.assert_not_called()
    assert "Return" not in svc._focused_passthrough_sent


def test_send_passthrough_gated_off_when_active_not_ttr(monkeypatch):
    svc = _make_svc(monkeypatch, game="cc")
    svc._strict_ttr_active = lambda: True
    svc._send_passthrough_to_focused("Return")
    svc._send_via_backend.assert_not_called()
    assert "Return" not in svc._focused_passthrough_sent


def test_send_passthrough_delivers_and_records(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: True
    svc._send_passthrough_to_focused("Return")
    svc._send_via_backend.assert_called_once_with("keydown", "100", "Return")
    assert svc._focused_passthrough_sent["Return"] == ("100", "Return")


def test_release_sends_to_recorded_target_even_after_state_change(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: True
    svc._send_passthrough_to_focused("Shift_L")
    svc._send_via_backend.reset_mock()
    svc._strict_ttr_active = lambda: False
    svc.window_manager._active = "999"
    svc._release_focused_passthrough("Shift_L")
    svc._send_via_backend.assert_called_once_with("keyup", "100", "Shift_L")
    assert "Shift_L" not in svc._focused_passthrough_sent


def test_release_noop_when_not_sent(monkeypatch):
    svc = _make_svc(monkeypatch)
    svc._release_focused_passthrough("Return")
    svc._send_via_backend.assert_not_called()


def test_drain_releases_all_recorded(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: True
    svc._send_passthrough_to_focused("Shift_L")
    svc._send_passthrough_to_focused("Control_L")
    svc._send_via_backend.reset_mock()
    svc._drain_focused_passthrough()
    sent = {c.args for c in svc._send_via_backend.call_args_list}
    assert ("keyup", "100", "Shift_L") in sent
    assert ("keyup", "100", "Control_L") in sent
    assert svc._focused_passthrough_sent == {}


def test_backspace_to_focused_uses_key_tap(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: True
    svc._send_backspace_to_focused()
    svc._send_via_backend.assert_called_once_with("key", "100", "BackSpace")


def test_backspace_to_focused_gated_off(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: False
    svc._send_backspace_to_focused()
    svc._send_via_backend.assert_not_called()


def test_duplicate_keydown_releases_prior_first(monkeypatch):
    svc = _make_svc(monkeypatch, active="100", game="ttr")
    svc._strict_ttr_active = lambda: True
    svc._send_passthrough_to_focused("Shift_L")          # records ("100","Shift_L")
    svc.window_manager._active = "200"                     # focus moved, no release seen
    svc._send_via_backend.reset_mock()
    svc._send_passthrough_to_focused("Shift_L")           # duplicate keydown
    calls = [c.args for c in svc._send_via_backend.call_args_list]
    # Prior entry released to its recorded target BEFORE the new keydown:
    assert calls == [("keyup", "100", "Shift_L"), ("keydown", "200", "Shift_L")]
    assert svc._focused_passthrough_sent["Shift_L"] == ("200", "Shift_L")
