import queue
from unittest.mock import MagicMock

from services.input_service import InputService
from utils.win32_integrity import Capability


def _svc(monkeypatch, cap, focused="w1", game="ttr"):
    wm = MagicMock()
    wm.get_active_window.return_value = focused
    wm.get_window_ids.return_value = ["w1", "w2"]
    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
        capability_provider=lambda hwnd: cap,
    )
    from utils import game_registry as gr
    reg = MagicMock()
    reg.get_game_for_window.return_value = game
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: reg)
    return s


def test_delivery_safe_true_when_ok(monkeypatch):
    assert _svc(monkeypatch, Capability.OK)._focused_strict_delivery_safe() is True


def test_delivery_unsafe_when_blocked(monkeypatch):
    assert _svc(monkeypatch, Capability.BLOCKED_UIPI)._focused_strict_delivery_safe() is False


def test_delivery_unsafe_when_unknown(monkeypatch):
    assert _svc(monkeypatch, Capability.UNKNOWN)._focused_strict_delivery_safe() is False


def test_delivery_safe_true_when_focus_not_ttr_game(monkeypatch):
    # Non-TTR focus (cc) has no TTR strict suppression to gate -> safe.
    assert _svc(monkeypatch, Capability.BLOCKED_UIPI, game="cc")._focused_strict_delivery_safe() is True


def test_delivery_safe_true_when_no_active_window(monkeypatch):
    s = _svc(monkeypatch, Capability.BLOCKED_UIPI)
    s.window_manager.get_active_window.return_value = None
    assert s._focused_strict_delivery_safe() is True
