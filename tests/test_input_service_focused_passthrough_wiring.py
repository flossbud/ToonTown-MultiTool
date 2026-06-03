"""Wiring tests: the run loop delivers non-movement keys to the focused toon
(skipping movement-as-movement), releases them on keyup, and drains on focus
loss / shutdown."""
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


def _make_svc(monkeypatch, keymap_manager=None):
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
        keymap_manager=keymap_manager,
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


def test_runloop_nonmovement_key_delivered_to_focused(monkeypatch):
    svc, q = _make_svc(monkeypatch)
    try:
        svc.start()
        # Put event AFTER start() so the startup seed drain cannot race with it.
        q.put(("keydown", "Return"))
        assert _wait(lambda: ("keydown", "100", "Return") in _calls(svc))
        assert "Return" in svc._focused_passthrough_sent
    finally:
        svc.shutdown()


def test_runloop_movement_key_not_via_passthrough(monkeypatch):
    svc, q = _make_svc(monkeypatch)
    try:
        svc.start()
        q.put(("keydown", "w"))          # movement: must NOT go via passthrough
        q.put(("keydown", "Escape"))     # non-movement sentinel: WILL go via passthrough
        # Once the sentinel is delivered, the loop has processed past "w".
        assert _wait(lambda: ("keydown", "100", "Escape") in _calls(svc))
        assert ("keydown", "100", "w") not in _calls(svc)
        assert "w" not in svc._focused_passthrough_sent
    finally:
        svc.shutdown()


def test_runloop_keyup_releases_focused(monkeypatch):
    svc, q = _make_svc(monkeypatch)
    try:
        svc.start()
        q.put(("keydown", "Return"))
        assert _wait(lambda: "Return" in svc._focused_passthrough_sent)
        q.put(("keyup", "Return"))
        assert _wait(lambda: ("keyup", "100", "Return") in _calls(svc))
        assert _wait(lambda: "Return" not in svc._focused_passthrough_sent)
    finally:
        svc.shutdown()


def test_runloop_cleanup_branch_drains_focused(monkeypatch):
    svc, q = _make_svc(monkeypatch)
    try:
        svc.start()
        q.put(("keydown", "Shift_L"))
        assert _wait(lambda: "Shift_L" in svc._focused_passthrough_sent)
        # Focus loss: point active window at an unrelated hwnd so
        # should_send_input() is False and the cleanup branch fires.
        svc.window_manager._active = "999999"
        assert _wait(lambda: ("keyup", "100", "Shift_L") in _calls(svc))
        assert _wait(lambda: svc._focused_passthrough_sent == {})
    finally:
        svc.shutdown()


def test_drain_on_focus_change_releases_registry(monkeypatch):
    """A focus CHANGE drains the focused-passthrough registry, releasing held
    keys to the window they were sent to (the primary stuck-key guard). Driven
    synchronously via _on_active_window_changed_for_grabber (no svc.start())."""
    svc, _q = _make_svc(monkeypatch)
    svc._send_via_backend = MagicMock()
    svc._send_passthrough_to_focused("Shift_L")
    assert "Shift_L" in svc._focused_passthrough_sent
    svc._send_via_backend.reset_mock()
    # Focus change away: the drain fires before any grabber teardown.
    svc._on_active_window_changed_for_grabber("")
    svc._send_via_backend.assert_any_call("keyup", "100", "Shift_L")
    assert svc._focused_passthrough_sent == {}


def test_release_all_keys_drains_focused_passthrough(monkeypatch):
    """release_all_keys drains the focused-passthrough registry so no key is
    left logically down on the focused toon. Driven synchronously (no start())."""
    svc, _q = _make_svc(monkeypatch)
    svc._send_via_backend = MagicMock()
    svc._send_passthrough_to_focused("Control_L")
    assert "Control_L" in svc._focused_passthrough_sent
    svc._send_via_backend.reset_mock()
    svc.release_all_keys()
    svc._send_via_backend.assert_any_call("keyup", "100", "Control_L")
    assert svc._focused_passthrough_sent == {}
