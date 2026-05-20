"""Verify InputService passes only CC window IDs to the wine bridge.

The bridge helper only knows about CC windows in its prefix; passing
the full window list (including non-CC windows) breaks the bridge's
cross_check_sort_order length comparison and forces an xlib fallback
that Wine ignores. This test pins the contract that the routing layer
filters before the bridge call.
"""

import queue
from unittest.mock import MagicMock, patch

import pytest

from services.input_service import InputService


class _FakeWindowManager:
    def __init__(self, ids, active):
        self._ids = list(ids)
        self._active = active
    def get_window_ids(self):
        return list(self._ids)
    def get_active_window(self):
        return self._active
    def assign_windows(self):
        pass


@pytest.fixture
def mixed_svc(monkeypatch):
    """Build an InputService with one TTR window and one CC window."""
    fake_registry = MagicMock()
    fake_registry.get_game_for_window.side_effect = (
        lambda wid: "ttr" if str(wid) == "100" else "cc"
    )
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    wm = _FakeWindowManager(ids=["100", "200"], active="100")

    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    return s


def test_cc_window_ids_returns_only_cc_subset(mixed_svc):
    """Helper returns CC-only IDs in left-to-right order."""
    assert mixed_svc._cc_window_ids() == ["200"]


def test_send_via_backend_passes_cc_only_ids_to_bridge(mixed_svc, monkeypatch):
    """When routing to a CC bg window in a mixed TTR+CC layout, the
    bridge MUST receive only the CC subset of window IDs. Otherwise
    cross_check_sort_order's length comparison fails and the bridge
    falls back to xlib which Wine ignores."""
    captured = {}

    def fake_send_to_window(win_id, window_ids, action, keysym, modifiers=None):
        captured["win_id"] = win_id
        captured["window_ids"] = list(window_ids)
        captured["action"] = action
        captured["keysym"] = keysym
        return True  # pretend bridge succeeded so xlib fallback doesn't run

    monkeypatch.setattr(
        "utils.wine_input_bridge.send_to_window", fake_send_to_window
    )

    mixed_svc._send_via_backend("keydown", "200", "w")

    assert captured["window_ids"] == ["200"]
    assert "100" not in captured["window_ids"]
    assert captured["win_id"] == "200"
    assert captured["action"] == "keydown"


def test_on_passthrough_key_passes_cc_only_ids_to_bridge(mixed_svc, monkeypatch):
    """The active-grab passthrough path has the same bug. Verify it
    also filters to CC-only. The slot only fires when the active
    window is CC, so set active to the CC window."""
    mixed_svc.window_manager._active = "200"

    captured = {}

    def fake_send_to_window(win_id, window_ids, action, keysym, modifiers=None):
        captured["win_id"] = win_id
        captured["window_ids"] = list(window_ids)
        return True

    monkeypatch.setattr(
        "utils.wine_input_bridge.send_to_window", fake_send_to_window
    )

    mixed_svc._on_passthrough_key("keydown", "w")

    assert captured["window_ids"] == ["200"]
    assert "100" not in captured["window_ids"]


def test_cc_only_setup_passes_all_windows(monkeypatch):
    """When all managed windows are CC (no TTR), the filter is a no-op:
    full window list is passed. This guards against regressing the
    CC+CC scenario the user has already validated."""
    fake_registry = MagicMock()
    fake_registry.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    wm = _FakeWindowManager(ids=["200", "201"], active="200")

    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    captured = {}

    def fake_send_to_window(win_id, window_ids, action, keysym, modifiers=None):
        captured["window_ids"] = list(window_ids)
        return True

    monkeypatch.setattr(
        "utils.wine_input_bridge.send_to_window", fake_send_to_window
    )

    s._send_via_backend("keydown", "201", "w")
    assert captured["window_ids"] == ["200", "201"]


def test_no_cc_windows_returns_empty(monkeypatch):
    """All-TTR layout: _cc_window_ids returns []. Bridge call site
    should not be reached in this case (TTR routing uses xlib backend
    directly), but the helper must not crash."""
    fake_registry = MagicMock()
    fake_registry.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    wm = _FakeWindowManager(ids=["100", "101"], active="100")
    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    assert s._cc_window_ids() == []
