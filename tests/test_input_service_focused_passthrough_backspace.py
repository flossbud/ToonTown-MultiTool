"""BackSpace reaches the focused TTR toon as a key-tap on the initial press,
delivered from the run loop, and is NOT recorded in the passthrough registry."""
import queue
import time
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


def _make_svc(monkeypatch):
    reg = MagicMock()
    reg.get_game_for_window.side_effect = lambda wid: "ttr"
    monkeypatch.setattr("utils.game_registry.GameRegistry.instance", lambda: reg)
    q = queue.Queue()
    svc = InputService(
        window_manager=_WM(),
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: q,
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=None,
    )
    svc._strict_ttr_active = lambda: True
    svc._send_via_backend = MagicMock()
    return svc, q


def _wait(cond, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def _calls(svc):
    return [c.args for c in svc._send_via_backend.call_args_list]


def test_runloop_backspace_delivered_to_focused(monkeypatch):
    svc, q = _make_svc(monkeypatch)
    try:
        svc.start()
        q.put(("keydown", "BackSpace"))
        assert _wait(lambda: ("key", "100", "BackSpace") in _calls(svc))
        assert "BackSpace" not in svc._focused_passthrough_sent
    finally:
        svc.shutdown()
