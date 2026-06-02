"""Verify that _send_via_backend never silently falls back to xdotool/XTEST
when the xlib backend failed to initialize.

XTEST re-triggers the Wayland input-control portal the app deliberately
avoids and can leave a stuck auto-repeating key. When _xlib_backend_failed
is True the event must be dropped. The user's explicit xdotool choice
(xlib=None, _xlib_backend_failed=False) must still work.
"""

import queue
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService


class _FakeWindowManager:
    def __init__(self):
        pass

    def get_window_ids(self):
        return []

    def get_active_window(self):
        return None

    def assign_windows(self):
        pass


def _make_svc(monkeypatch):
    """Build an InputService with mock collaborators. Does NOT start the
    thread. Monkeypatches GameRegistry so all windows resolve as 'ttr',
    bypassing the CC wine-bridge early-return in _send_via_backend."""
    fake_registry = MagicMock()
    fake_registry.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    wm = _FakeWindowManager()

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [],
        get_movement_modes=lambda: [],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: None),
        get_keymap_assignments=lambda: [],
        keymap_manager=MagicMock(),
    )
    return svc


# ---------------------------------------------------------------------------
# 1. No XTEST when xlib failed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action,keysym,modifiers", [
    ("keydown", "w", None),
    ("key", "w", ["ctrl"]),
])
def test_no_xtest_when_xlib_failed(monkeypatch, action, keysym, modifiers):
    """When xlib failed to init, _safe_run (xdotool/XTEST) must NOT be
    called regardless of action type."""
    svc = _make_svc(monkeypatch)

    svc._xlib = None
    svc._xlib_backend_failed = True
    svc._xlib_unavailable_logged = False

    svc._safe_run = MagicMock()
    svc._send_via_backend(action, "100", keysym, modifiers)

    svc._safe_run.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Drop surfaces once
# ---------------------------------------------------------------------------

def test_drop_surfaces_once(monkeypatch):
    """input_log.emit must fire exactly once across multiple dropped events,
    and _safe_run must never be called."""
    svc = _make_svc(monkeypatch)

    svc._xlib = None
    svc._xlib_backend_failed = True
    svc._xlib_unavailable_logged = False
    svc.logging_enabled = True

    svc.input_log = MagicMock()
    svc._safe_run = MagicMock()

    svc._send_via_backend("keydown", "100", "w")
    svc._send_via_backend("keyup", "100", "w")

    svc.input_log.emit.assert_called_once()
    svc._safe_run.assert_not_called()
    assert svc._xlib_unavailable_logged is True


# ---------------------------------------------------------------------------
# 3. Explicit xdotool still runs
# ---------------------------------------------------------------------------

def test_explicit_xdotool_runs(monkeypatch):
    """When xlib is None and _xlib_backend_failed is False (explicit xdotool
    choice), _safe_run must be called with the expected arguments."""
    svc = _make_svc(monkeypatch)

    svc._xlib = None
    svc._xlib_backend_failed = False
    svc._safe_run = MagicMock(return_value=True)

    svc._send_via_backend("keydown", "100", "w")

    svc._safe_run.assert_called_once_with(
        ["xdotool", "keydown", "--window", "100", "w"]
    )


# ---------------------------------------------------------------------------
# 4. Xlib path unaffected
# ---------------------------------------------------------------------------

def test_xlib_path_unaffected(monkeypatch):
    """When a live xlib backend is present, it must be used and _safe_run
    must not be called."""
    svc = _make_svc(monkeypatch)

    svc._xlib = MagicMock()
    svc._xlib.send_keydown.return_value = True
    svc._safe_run = MagicMock()

    svc._send_via_backend("keydown", "100", "w")

    svc._xlib.send_keydown.assert_called_once_with("100", "w")
    svc._safe_run.assert_not_called()
