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


# ── Integration tests: drive the run loop and assert on state ────────────

import queue
import time


class _DriveWindowManager:
    """Window manager fixture for tests that drive the run loop. Mutable
    _active so tests can simulate focus changes."""
    def __init__(self, window_ids, active):
        self._ids = list(window_ids)
        self._active = active

    def get_active_window(self):
        return self._active

    def get_window_ids(self):
        return list(self._ids)

    def assign_windows(self):
        pass


def _make_drive_service(chat):
    """Build an InputService with two windows where '1001' is the focused
    (multitool) window and '1002' is the background toon. The `chat` list
    is captured by closure so tests can mutate it mid-run via `chat[:] = ...`
    to simulate the user toggling chat buttons live."""
    wm = _DriveWindowManager(window_ids=["1001", "1002"], active="1001")
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: (
        "1001" if key == "multitool_window_id" else default
    )
    q = queue.Queue()
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["WASD", "WASD"],
        get_event_queue_func=lambda: q,
        settings_manager=settings,
        get_chat_enabled=lambda: list(chat),
    )
    svc._xlib = MagicMock()
    svc._xlib.send_keydown.return_value = True
    svc._xlib.send_keyup.return_value = True
    svc._xlib.send_key.return_value = True
    return svc, q


def _drive_no_stop(svc, q, events, drain_timeout=0.5, settle=0.05):
    """Push events; start the service if not running; wait for queue to drain
    and one settle period. Does NOT stop the service so tests can inspect
    state between batches."""
    for ev in events:
        q.put(ev)
    if not svc.running:
        svc.start()
    deadline = time.monotonic() + drain_timeout
    while time.monotonic() < deadline and not q.empty():
        time.sleep(0.005)
    time.sleep(settle)


def test_phantom_does_not_activate_when_gate_closed():
    """Bg toon has chat off → gate closed. Typing 5 printable chars must
    leave _phantom_active False and _phantom_char_count at 0."""
    chat = [False, False]
    svc, q = _make_drive_service(chat)
    try:
        _drive_no_stop(svc, q, [
            ("keydown", "h"), ("keyup", "h"),
            ("keydown", "i"), ("keyup", "i"),
            ("keydown", "x"), ("keyup", "x"),
            ("keydown", "y"), ("keyup", "y"),
            ("keydown", "z"), ("keyup", "z"),
        ])
        assert svc._phantom_active is False
        assert svc._phantom_char_count == 0
    finally:
        svc.stop(wait=True)


def test_phantom_activates_after_three_chars_when_gate_open():
    """Bg toon has chat on → gate open. Three unique printable chars must
    activate phantom (preserves current behavior)."""
    chat = [False, True]
    svc, q = _make_drive_service(chat)
    try:
        _drive_no_stop(svc, q, [
            ("keydown", "h"), ("keyup", "h"),
            ("keydown", "i"), ("keyup", "i"),
            ("keydown", "x"), ("keyup", "x"),
        ])
        assert svc._phantom_active is True
    finally:
        svc.stop(wait=True)


def test_mid_burst_gate_close_resets_counter():
    """Counter increments while gate open; flipping gate closed mid-burst
    resets the counter to 0 on the next printable keydown."""
    chat = [False, True]  # gate open
    svc, q = _make_drive_service(chat)
    try:
        # Two chars with gate open
        _drive_no_stop(svc, q, [
            ("keydown", "h"), ("keyup", "h"),
            ("keydown", "i"), ("keyup", "i"),
        ])
        assert svc._phantom_char_count == 2

        # User toggles chat off on the only chat-enabled bg toon
        chat[:] = [False, False]

        # Next printable char must reset the counter (and not activate phantom)
        _drive_no_stop(svc, q, [("keydown", "x"), ("keyup", "x")])
        assert svc._phantom_char_count == 0
        assert svc._phantom_active is False
    finally:
        svc.stop(wait=True)
