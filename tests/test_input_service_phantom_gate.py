"""Tests for InputService._phantom_gate_open and the chat-disabled phantom bypass.

The rule: phantom (whisper-reply) detection only operates when at least one
ENABLED background toon has chat ENABLED. The foreground toon is excluded
from the check because its chat state does not affect what gets broadcast
to other toons.

See: docs/superpowers/specs/2026-05-26-chat-disabled-phantom-bypass-design.md
"""

from unittest.mock import MagicMock

from services.input_service import InputService


class _FakeWindowManager:
    def __init__(self, window_ids, active_window):
        self._wids = list(window_ids)
        self._active = active_window

    def get_active_window(self):
        return self._active

    def get_window_ids(self):
        return list(self._wids)

    def assign_windows(self):
        pass


def _make_service(enabled, chat, window_ids, active_window, get_chat_enabled_none=False):
    """Build an InputService whose helpers return the given fixture state."""
    wm = _FakeWindowManager(window_ids=window_ids, active_window=active_window)
    return InputService(
        window_manager=wm,
        get_enabled_toons=lambda: list(enabled),
        get_movement_modes=lambda: ["WASD"] * len(enabled),
        get_event_queue_func=lambda: None,
        settings_manager=MagicMock(),
        get_chat_enabled=None if get_chat_enabled_none else (lambda: list(chat)),
    )


def test_gate_closed_when_no_bg_toons_have_chat_enabled():
    """Two enabled toons; bg toon (index 1) has chat off; foreground excluded.
    Gate must be closed: phantom serves no purpose."""
    svc = _make_service(
        enabled=[True, True],
        chat=[False, False],
        window_ids=["w1", "w2"],
        active_window="w1",
    )
    assert svc._phantom_gate_open() is False


def test_gate_open_when_one_bg_toon_has_chat_enabled():
    """Bg toon at index 1 has chat on. Gate must be open."""
    svc = _make_service(
        enabled=[True, True],
        chat=[False, True],
        window_ids=["w1", "w2"],
        active_window="w1",
    )
    assert svc._phantom_gate_open() is True


def test_gate_closed_when_only_chat_enabled_toon_is_foreground():
    """Foreground (toon 0) has chat on, bg (toon 1) has chat off. Foreground
    is excluded from the gate check, so gate must be closed."""
    svc = _make_service(
        enabled=[True, True],
        chat=[True, False],
        window_ids=["w1", "w2"],
        active_window="w1",
    )
    assert svc._phantom_gate_open() is False


def test_gate_closed_when_no_enabled_toons():
    """No enabled toons at all. Gate must be closed."""
    svc = _make_service(
        enabled=[False, False],
        chat=[True, True],
        window_ids=["w1", "w2"],
        active_window="w1",
    )
    assert svc._phantom_gate_open() is False


def test_gate_open_when_get_chat_enabled_is_none():
    """Legacy/test fixtures may not wire get_chat_enabled. Default to 'all
    enabled' (matches the existing _is_chat_allowed convention) so the gate
    opens whenever any enabled bg toon exists."""
    svc = _make_service(
        enabled=[True, True],
        chat=[],  # ignored
        window_ids=["w1", "w2"],
        active_window="w1",
        get_chat_enabled_none=True,
    )
    assert svc._phantom_gate_open() is True


def test_gate_closed_when_chat_list_is_shorter_than_enabled():
    """Defensive: chat list might lag enabled list briefly during UI updates.
    Helper must not raise IndexError; missing entries are treated as 'not
    chat-enabled'."""
    svc = _make_service(
        enabled=[True, True, True],
        chat=[True],  # only one entry for three toons
        window_ids=["w1", "w2", "w3"],
        active_window="w1",
    )
    # bg toons are index 1 and 2; chat list only has index 0; gate closed.
    assert svc._phantom_gate_open() is False
