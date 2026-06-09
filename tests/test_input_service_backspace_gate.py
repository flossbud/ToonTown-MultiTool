"""Background Backspace must follow the same per-toon chat permission as the
typed-character path (_is_chat_allowed). In focused_only the effective chat
list is all-False, so no background toon receives Backspace.

See: docs/superpowers/specs/2026-06-09-chat-handling-logic-dropdown-design.md
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.input_service import InputService


def _make_service(chat_enabled):
    wm = SimpleNamespace(
        get_active_window=lambda: "wA",
        get_window_ids=lambda: ["wA", "wB", "wC"],
    )
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True, True],
        get_movement_modes=lambda: ["WASD", "WASD", "WASD"],
        get_event_queue_func=lambda: None,
        settings_manager=MagicMock(),
        get_chat_enabled=lambda: chat_enabled,
        get_chat_handling_mode=lambda: "per_toon",
    )
    svc._xlib = MagicMock()
    svc._xlib_backend_failed = False
    svc._send_via_backend = MagicMock()
    return svc


def test_backspace_skips_chat_blocked_background_toon():
    svc = _make_service(chat_enabled=[True, False, True])
    try:
        svc._send_backspace_to_background([True, True, True], [0, 0, 0])
        calls = [c.args for c in svc._send_via_backend.call_args_list]
        targets = [args[1] for args in calls]
        assert "wB" not in targets   # chat-blocked background toon
        assert "wA" not in targets   # focused window excluded
        # the allowed background toon gets exactly a BackSpace, not some other key
        assert ("key", "wC", "BackSpace") in calls
    finally:
        svc.shutdown()


def test_backspace_blocks_all_background_when_focused_only_all_false():
    svc = _make_service(chat_enabled=[False, False, False])
    try:
        svc._send_backspace_to_background([True, True, True], [0, 0, 0])
        assert svc._send_via_backend.call_count == 0
    finally:
        svc.shutdown()


def test_backspace_treats_missing_chat_entries_as_denied():
    """Defensive: when the effective chat list is shorter than the window
    list (it can briefly lag during UI updates), the missing index is treated
    as not-chat-allowed and that background toon is skipped, never raising."""
    svc = _make_service(chat_enabled=[True, True])  # only two entries, three windows
    try:
        svc._send_backspace_to_background([True, True, True], [0, 0, 0])
        targets = [c.args[1] for c in svc._send_via_backend.call_args_list]
        assert "wB" in targets       # index 1 present and allowed
        assert "wC" not in targets   # index 2 missing from chat list -> denied
        assert "wA" not in targets   # focused window excluded
    finally:
        svc.shutdown()
