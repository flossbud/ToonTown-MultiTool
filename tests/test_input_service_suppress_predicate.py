"""Tests for InputService._suppress_predicate, the bridge from HotkeyManager to the platform grabber."""

from __future__ import annotations

from unittest.mock import MagicMock

from services.input_service import InputService


def _make_service():
    wm = MagicMock()
    return InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [],
        get_movement_modes=lambda: [],
        get_event_queue_func=lambda: None,
    )


class TestSuppressPredicate:
    def test_returns_false_when_grabber_none(self):
        svc = _make_service()
        svc._key_grabber = None
        assert svc._suppress_predicate("Up") is False

    def test_returns_false_when_grabber_has_no_should_suppress(self):
        # The Linux grabber does not expose should_suppress
        svc = _make_service()
        grabber = MagicMock(spec=[])  # no attrs at all
        svc._key_grabber = grabber
        assert svc._suppress_predicate("Up") is False

    def test_delegates_to_grabber_should_suppress(self):
        svc = _make_service()
        grabber = MagicMock()
        grabber.should_suppress.return_value = True
        svc._key_grabber = grabber
        assert svc._suppress_predicate("Up") is True
        grabber.should_suppress.assert_called_once_with("Up")

    def test_returns_false_when_grabber_returns_false(self):
        svc = _make_service()
        grabber = MagicMock()
        grabber.should_suppress.return_value = False
        svc._key_grabber = grabber
        assert svc._suppress_predicate("Up") is False
