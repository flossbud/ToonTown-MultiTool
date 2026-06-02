"""Tests for xlib backend init failure classification.

Verifies that _xlib_backend_failed is set correctly to distinguish
"xlib was requested but connect() raised" from "user chose xdotool".
This flag is consumed by _send_via_backend (Task 2) to refuse the silent
xdotool/XTEST fallback that re-triggers the Wayland input-control portal.
"""

import queue
from unittest.mock import MagicMock

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


def _make_svc(settings_get_side_effect):
    """Build an InputService with mock collaborators. Does NOT start the thread."""
    settings_manager = MagicMock()
    settings_manager.get.side_effect = settings_get_side_effect

    wm = _FakeWindowManager()

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [],
        get_movement_modes=lambda: [],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=settings_manager,
        get_keymap_assignments=lambda: [],
        keymap_manager=MagicMock(),
    )
    return svc


def test_connect_failure_sets_flag(monkeypatch):
    """connect() raising on xlib backend sets _xlib_backend_failed=True and
    leaves _xlib as None."""

    class _FailingBackend:
        def connect(self):
            raise RuntimeError("no display")

    monkeypatch.setattr("utils.xlib_backend.XlibBackend", _FailingBackend)

    svc = _make_svc(
        lambda key, default=None: "xlib" if key == "input_backend" else default
    )
    svc._apply_backend_setting()

    assert svc._xlib is None
    assert svc._xlib_backend_failed is True


def test_failure_message_is_not_misleading(monkeypatch, capsys):
    """Failure stdout must NOT mention 'falling back to xdotool' and MUST
    mention 'refusing xdotool/XTEST fallback'."""

    class _FailingBackend:
        def connect(self):
            raise RuntimeError("no display")

    monkeypatch.setattr("utils.xlib_backend.XlibBackend", _FailingBackend)

    svc = _make_svc(
        lambda key, default=None: "xlib" if key == "input_backend" else default
    )
    svc._apply_backend_setting()

    captured = capsys.readouterr()
    assert "falling back to xdotool" not in captured.out
    assert "refusing xdotool/XTEST fallback" in captured.out


def test_explicit_xdotool_clears_flag_and_disconnects():
    """When the user explicitly selects xdotool, _xlib_backend_failed is
    cleared to False and any existing backend is disconnected."""
    svc = _make_svc(
        lambda key, default=None: "xdotool" if key == "input_backend" else default
    )

    mock_backend = MagicMock()
    svc._xlib = mock_backend
    svc._xlib_backend_failed = True
    svc._xlib_unavailable_logged = True

    svc._apply_backend_setting()

    assert svc._xlib is None
    assert svc._xlib_backend_failed is False
    assert svc._xlib_unavailable_logged is False
    mock_backend.disconnect.assert_called_once()


def test_ongoing_failure_preserves_unavailable_logged(monkeypatch):
    """A re-failing reconnect must NOT reset _xlib_unavailable_logged.

    Simulates Task 2 having already fired the one-shot "input delivery
    disabled" log during a prior drop; verifies the guard survives a
    subsequent _apply_backend_setting() call that also fails.
    """

    class _FailingBackend:
        def connect(self):
            raise RuntimeError("no display")

    monkeypatch.setattr("utils.xlib_backend.XlibBackend", _FailingBackend)

    svc = _make_svc(
        lambda key, default=None: "xlib" if key == "input_backend" else default
    )

    # Preconditions: no live backend, one-shot guard already fired.
    assert svc._xlib is None
    svc._xlib_unavailable_logged = True

    svc._apply_backend_setting()

    # The failure branch must set the failed flag …
    assert svc._xlib_backend_failed is True
    # … and must NOT reset the one-shot guard (only recovery resets it).
    assert svc._xlib_unavailable_logged is True


def test_connect_success_clears_both_flags(monkeypatch):
    """Recovery after a real failure clears both _xlib_backend_failed and
    _xlib_unavailable_logged, and leaves _xlib set.

    Goes through a genuine failure first, then swaps in a working backend
    and calls _apply_backend_setting() again to exercise the recovery path.
    """
    class _FailingBackend:
        def connect(self):
            raise RuntimeError("no display")

    monkeypatch.setattr("utils.xlib_backend.XlibBackend", _FailingBackend)

    svc = _make_svc(
        lambda key, default=None: "xlib" if key == "input_backend" else default
    )

    # Step 1: trigger a real failure.
    svc._apply_backend_setting()
    assert svc._xlib is None
    assert svc._xlib_backend_failed is True
    # Simulate Task 2 having logged a drop message during the failed episode.
    svc._xlib_unavailable_logged = True

    # Step 2: swap in a working backend; _xlib is still None so the
    # if self._xlib is None: guard re-attempts the connect.
    class _SucceedingBackend:
        def connect(self):
            pass  # success

    monkeypatch.setattr("utils.xlib_backend.XlibBackend", _SucceedingBackend)
    svc._apply_backend_setting()

    # Step 3: recovery must clear both failure flags and leave _xlib set.
    assert svc._xlib is not None
    assert svc._xlib_backend_failed is False
    assert svc._xlib_unavailable_logged is False
