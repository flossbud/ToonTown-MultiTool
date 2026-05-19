"""Tests for InputService's wiring of the X11 movement grabber:
the should_consume callback, the conflicting-keysyms helper, and
the lifecycle hooks."""

import queue
from unittest.mock import MagicMock

import pytest

from services import input_service
from services.input_service import (
    InputService,
    _conflicting_canonical_keysyms,
    _passthrough_keysyms_for_canonical,
)


def test_conflicting_keysyms_wasd_canonical_returns_arrows():
    assert _conflicting_canonical_keysyms("wasd") == ("Up", "Down", "Left", "Right")


def test_conflicting_keysyms_arrows_canonical_returns_wasd():
    assert _conflicting_canonical_keysyms("arrows") == ("w", "a", "s", "d")


def test_conflicting_keysyms_unknown_canonical_returns_empty():
    assert _conflicting_canonical_keysyms("ijkl") == ()


@pytest.fixture
def svc(monkeypatch):
    wm = MagicMock()
    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    return s


def test_should_consume_false_when_chat_active(svc):
    svc.global_chat_active = True
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_false_when_no_active_window(svc):
    svc.window_manager.get_active_window.return_value = None
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_true_when_active_window_is_cc(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)
    assert svc._should_consume_grabbed_key("Up") is True


def test_should_consume_false_when_active_window_is_ttr(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_false_when_registry_lookup_raises(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: (_ for _ in ()).throw(RuntimeError("registry borked")))
    assert svc._should_consume_grabbed_key("Up") is False


def test_on_grabbed_key_enqueues_into_event_queue(svc):
    q = queue.Queue()
    svc.get_event_queue = lambda: q
    svc._on_grabbed_key("keydown", "Up")
    svc._on_grabbed_key("keyup", "Up")
    assert q.get_nowait() == ("keydown", "Up")
    assert q.get_nowait() == ("keyup", "Up")


def test_on_grabbed_key_swallows_full_queue(svc, capsys):
    full_q = queue.Queue(maxsize=1)
    full_q.put_nowait(("keydown", "X"))  # fill it
    svc.get_event_queue = lambda: full_q
    # Must not raise; the print falls into capsys.
    svc._on_grabbed_key("keydown", "Up")


def test_start_key_grabber_skipped_when_xlib_unavailable(svc, monkeypatch):
    """If python-xlib isn't available, the grabber attribute stays None
    and start_key_grabber returns silently."""
    import utils.x11_movement_grabber as gm
    monkeypatch.setattr(gm, "xlib_available", lambda: False)
    svc._start_key_grabber()
    assert svc._key_grabber is None


def test_start_key_grabber_skipped_when_grabber_start_returns_false(svc, monkeypatch):
    """Grabber instantiated but start() fails (e.g. cannot open display);
    InputService clears the attribute."""
    import utils.x11_movement_grabber as gm
    monkeypatch.setattr(gm, "xlib_available", lambda: True)

    class FakeGrabber:
        def start(self, **_):
            return False
        def stop(self):
            pass
    monkeypatch.setattr(gm, "MovementKeyGrabber", FakeGrabber)

    svc._start_key_grabber()
    assert svc._key_grabber is None


def test_shutdown_calls_grabber_stop(svc, monkeypatch):
    fake = MagicMock()
    svc._key_grabber = fake
    monkeypatch.setattr(input_service, "wine_input_bridge", MagicMock(), raising=False)
    svc.shutdown()
    fake.stop.assert_called_once()
    assert svc._key_grabber is None


def test_passthrough_keysyms_for_wasd_canonical_includes_movement_modifiers_letters():
    keys = _passthrough_keysyms_for_canonical("wasd")
    # Canonical movement keys
    assert "w" in keys and "a" in keys and "s" in keys and "d" in keys
    # Modifiers
    assert "Shift_L" in keys and "Control_L" in keys and "Alt_L" in keys
    # Common action keys
    assert "space" in keys and "Tab" in keys and "Escape" in keys
    # Common letters used in CC bindings (q=gags, e=tasks)
    assert "q" in keys and "e" in keys
    # Digits
    assert "1" in keys and "9" in keys


def test_passthrough_keysyms_for_arrows_canonical_includes_arrows():
    keys = _passthrough_keysyms_for_canonical("arrows")
    assert "Up" in keys and "Down" in keys and "Left" in keys and "Right" in keys


def test_on_passthrough_key_no_active_window_is_a_noop(svc):
    svc.window_manager.get_active_window.return_value = None
    # Must not raise even though no bridge call will succeed.
    svc._on_passthrough_key("keydown", "w")


def test_on_passthrough_key_non_cc_window_is_a_noop(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    bridge = MagicMock()
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", bridge)

    svc._on_passthrough_key("keydown", "w")

    bridge.assert_not_called()


def test_on_passthrough_key_cc_window_routes_to_wine_bridge(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    svc.window_manager.get_window_ids.return_value = ["w1", "w2"]
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    bridge = MagicMock()
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", bridge)

    svc._on_passthrough_key("keydown", "w")

    bridge.assert_called_once_with("w1", ["w1", "w2"], "keydown", "w")


def test_on_passthrough_key_swallows_bridge_exceptions(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    svc.window_manager.get_window_ids.return_value = ["w1"]
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    def boom(*_args, **_kw):
        raise RuntimeError("bridge unavailable")
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", boom)

    # Must not raise.
    svc._on_passthrough_key("keydown", "w")
