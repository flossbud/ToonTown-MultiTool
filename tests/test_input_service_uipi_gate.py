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


def _svc_grab(monkeypatch, cap, game="ttr"):
    s = _svc(monkeypatch, cap, game=game)
    s._key_grabber = MagicMock()
    s._ttr_grabs_active = True
    s._xlib = MagicMock()                       # delivery backend present
    s.settings_manager.get.return_value = True  # strict toggle ON
    return s


import pytest


@pytest.mark.parametrize("cap", [Capability.BLOCKED_UIPI, Capability.UNKNOWN])
def test_strict_active_false_when_focused_not_deliverable(monkeypatch, cap):
    assert _svc_grab(monkeypatch, cap)._strict_ttr_active() is False


def test_strict_active_true_when_focused_ok(monkeypatch):
    assert _svc_grab(monkeypatch, Capability.OK)._strict_ttr_active() is True


@pytest.mark.parametrize("cap", [Capability.BLOCKED_UIPI, Capability.UNKNOWN])
def test_should_consume_false_when_focused_not_deliverable(monkeypatch, cap):
    s = _svc_grab(monkeypatch, cap)
    s.global_chat_active = False
    assert s._should_consume_grabbed_key("Up") is False


def test_should_consume_true_when_focused_ok(monkeypatch):
    s = _svc_grab(monkeypatch, Capability.OK)
    s.global_chat_active = False
    assert s._should_consume_grabbed_key("Up") is True


@pytest.mark.parametrize("cap", [Capability.BLOCKED_UIPI, Capability.UNKNOWN])
def test_focus_install_skips_route_all_when_not_deliverable(monkeypatch, cap):
    s = _svc_grab(monkeypatch, cap)
    grab = s._key_grabber
    s._intended_ttr_strict = False
    s.window_manager.get_window_ids.return_value = ["w1"]
    s._canonical_set_for_toon_index = lambda i: "wasd"
    s._on_active_window_changed_for_grabber("w1")
    grab.install_grabs.assert_not_called()
    grab.uninstall_grabs.assert_called()
    assert s._intended_ttr_strict is False


def test_focus_install_route_all_when_ok(monkeypatch):
    s = _svc_grab(monkeypatch, Capability.OK)
    grab = s._key_grabber
    s.window_manager.get_window_ids.return_value = ["w1"]
    s._canonical_set_for_toon_index = lambda i: "wasd"
    s.global_chat_active = False
    s._phantom_active = False
    s._on_active_window_changed_for_grabber("w1")
    grab.install_grabs.assert_called()          # OK -> route_all installs as before


def test_resync_reinstall_skips_route_all_when_blocked(monkeypatch):
    # When capture (chat/phantom) closes and the focused TTR window is blocked,
    # the resync reinstall path must NOT reinstall route_all.
    s = _svc_grab(monkeypatch, Capability.BLOCKED_UIPI)
    grab = s._key_grabber
    s._intended_ttr_strict = True
    s.global_chat_active = False
    s._phantom_active = False
    s.window_manager.get_window_ids.return_value = ["w1"]
    s._canonical_set_for_toon_index = lambda i: "wasd"
    s._resync_grabs_for_input_capture(False)
    grab.install_grabs.assert_not_called()
