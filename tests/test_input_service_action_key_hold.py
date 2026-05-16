import queue
import time
from unittest.mock import MagicMock

from services.input_service import InputService


class _FakeWindowManager:
    def __init__(self, window_ids=None, active=None):
        self._ids = window_ids or ["1001", "1002"]
        self._active = active
    def get_active_window(self):
        return self._active
    def get_window_ids(self):
        return list(self._ids)
    def assign_windows(self):
        pass


def _make_service(active_window="1001", window_ids=None):
    """Build an InputService with a mocked xlib backend.

    Default config: 2 windows; "1001" is focused (real keyboard handles it),
    "1002" is the background toon we forward to.
    """
    wm = _FakeWindowManager(window_ids=window_ids or ["1001", "1002"], active=active_window)
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
    )
    svc._xlib = MagicMock()
    svc._xlib.send_keydown.return_value = True
    svc._xlib.send_keyup.return_value = True
    svc._xlib.send_key.return_value = True
    return svc, q


def _drive(svc, q, events, settle=0.05):
    """Push events, start the service, wait for them to drain, stop."""
    for ev in events:
        q.put(ev)
    svc.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not q.empty():
        time.sleep(0.005)
    time.sleep(settle)
    svc.stop(wait=True)


def test_action_keydown_helper_dispatches_to_bg_only():
    svc, _ = _make_service(active_window="1001", window_ids=["1001", "1002"])

    svc._send_action_keydown_to_bg("Delete", enabled=[True, True], assignments=[0, 0])

    # Focused window 1001 must NOT receive (real keyboard handles it).
    # Background window 1002 must receive exactly one keydown for "Delete".
    calls = [c.args for c in svc._xlib.send_keydown.call_args_list]
    assert calls == [("1002", "Delete")], f"unexpected keydown calls: {calls}"
    assert svc._xlib.send_keyup.call_count == 0
    assert svc._xlib.send_key.call_count == 0


def test_action_keyup_helper_dispatches_to_bg_only():
    svc, _ = _make_service(active_window="1001", window_ids=["1001", "1002"])

    svc._send_action_keyup_to_bg("Delete", enabled=[True, True], assignments=[0, 0])

    calls = [c.args for c in svc._xlib.send_keyup.call_args_list]
    assert calls == [("1002", "Delete")]
    assert svc._xlib.send_keydown.call_count == 0


def test_action_helpers_have_action_held_set_initialized():
    svc, _ = _make_service()
    assert hasattr(svc, "action_held")
    assert svc.action_held == set()


def test_holding_action_key_sends_keydown_once_then_keyup_on_release():
    """Repro: holding Delete (TTR Perform Action) must send ONE keydown and
    ONE keyup to each background toon, not the legacy tap. Autorepeat
    keydown events from the OS must be suppressed by `action_held`."""
    svc, q = _make_service()

    _drive(svc, q, [
        ("keydown", "Delete"),
        ("keydown", "Delete"),  # OS autorepeat
        ("keydown", "Delete"),  # OS autorepeat
        ("keyup",   "Delete"),
    ])

    kd = [c.args for c in svc._xlib.send_keydown.call_args_list if c.args[1] == "Delete"]
    ku = [c.args for c in svc._xlib.send_keyup.call_args_list   if c.args[1] == "Delete"]
    # Exactly one keydown and one keyup per background window:
    assert kd == [("1002", "Delete")], f"keydowns: {kd}"
    assert ku == [("1002", "Delete")], f"keyups: {ku}"
    # No legacy tap path:
    tap_calls = [c for c in svc._xlib.send_key.call_args_list if c.args[1] == "Delete"]
    assert tap_calls == [], f"unexpected tap: {tap_calls}"


def test_action_held_drains_when_chat_opens():
    """Hold Delete, then press Enter to open chat. Background toons must
    receive a keyup for Delete BEFORE Return triggers chat behavior, so
    Delete doesn't stay 'held' on bg toons indefinitely."""
    svc, q = _make_service()

    _drive(svc, q, [
        ("keydown", "Delete"),
        ("keydown", "Return"),  # Opens chat
    ])

    # Background window 1002 should have received a keyup for Delete:
    delete_keyups = [
        c.args for c in svc._xlib.send_keyup.call_args_list if c.args[1] == "Delete"
    ]
    assert delete_keyups == [("1002", "Delete")], (
        f"expected one Delete keyup on chat open, got: {delete_keyups}"
    )
    # action_held should be empty after the drain:
    assert svc.action_held == set(), f"action_held leaked: {svc.action_held}"


def test_action_held_drains_on_focus_loss():
    """Hold Delete, then have the user alt-tab away (active window becomes
    something that is neither a toon window nor the multitool). The cleanup
    branch in the run loop must release Delete on background toons."""
    svc, q = _make_service()

    # Step 1: prime action_held by pressing Delete
    q.put(("keydown", "Delete"))
    svc.start()
    # Wait for the keydown to register
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and ("Delete" not in svc.action_held):
        time.sleep(0.005)
    assert "Delete" in svc.action_held, "precondition: keydown did not register"

    # Step 2: simulate focus loss by pointing window manager at an unrelated hwnd
    svc.window_manager._active = "999999"  # not in window_ids, not multitool

    # Wait for the loop's should_send_input() cleanup branch to fire
    time.sleep(0.1)
    svc.stop(wait=True)

    delete_keyups = [
        c.args for c in svc._xlib.send_keyup.call_args_list if c.args[1] == "Delete"
    ]
    # On focus loss the original "focused" toon is no longer active, so the
    # drain treats every enabled toon as a background recipient.
    assert ("1002", "Delete") in delete_keyups, (
        f"expected Delete keyup on focus loss, got: {delete_keyups}"
    )
    assert svc.action_held == set()


def test_action_held_drains_on_release_all_keys():
    """release_all_keys is invoked on shutdown and must clear action_held
    so a held Delete doesn't linger after the app exits."""
    svc, q = _make_service()

    # Prime action_held without triggering the run-loop's own release_all_keys
    # (which happens in the finally of stop()). We simulate the keydown directly.
    q.put(("keydown", "Delete"))
    svc.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and ("Delete" not in svc.action_held):
        time.sleep(0.005)
    assert "Delete" in svc.action_held, "precondition: Delete should be held"

    svc._xlib.send_keyup.reset_mock()
    svc.release_all_keys()

    delete_keyups = [
        c.args for c in svc._xlib.send_keyup.call_args_list if c.args[1] == "Delete"
    ]
    # release_all_keys runs after focus-loss-like cleanup so both windows are bg recipients:
    assert ("1002", "Delete") in delete_keyups, (
        f"expected Delete keyup on release_all_keys, got: {delete_keyups}"
    )
    assert svc.action_held == set()

    svc.stop(wait=True)


def test_typing_in_chat_uses_tap_path_not_held_path():
    """When chat is active, pressing a printable key must use the existing
    typing/tap path so the character appears in TTR's chatbox. The new
    held-action path must NOT engage.

    Note: we use a non-movement printable key ("h") because WASD movement
    keys take a different filtered branch in legacy (no keymap_manager) mode.
    The spirit of the test is: printable typing should not engage the held
    action path.
    """
    svc, q = _make_service()
    svc.global_chat_active = True  # simulate chat already open

    _drive(svc, q, [("keydown", "h"), ("keyup", "h")])

    # Should NOT have called send_keydown for "h" (that's the held path):
    keydowns_for_h = [
        c.args for c in svc._xlib.send_keydown.call_args_list if c.args[1] == "h"
    ]
    assert keydowns_for_h == [], (
        f"chat typing should use tap path, but got keydowns: {keydowns_for_h}"
    )
    # Should have used send_key (the tap path) for "h":
    taps_for_h = [
        c.args for c in svc._xlib.send_key.call_args_list if c.args[1] == "h"
    ]
    assert taps_for_h, "chat typing did not reach the tap path"
    # action_held must remain empty:
    assert svc.action_held == set()
