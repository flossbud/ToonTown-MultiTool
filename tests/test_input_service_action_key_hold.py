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
