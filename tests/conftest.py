import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Monkeypatch xevent to work with fake objects in tests
from unittest.mock import MagicMock
from Xlib.protocol import event as xevent_orig

_original_button_press = xevent_orig.ButtonPress
_original_button_release = xevent_orig.ButtonRelease
_original_motion_notify = xevent_orig.MotionNotify


class _MockEvent:
    """Minimal mock event that captures attributes without struct packing."""
    type = None  # Override in subclasses

    def __init__(self, **kwargs):
        self.detail = 0
        self.time = 0
        self.root = None
        self.window = None
        self.same_screen = 0
        self.child = None
        self.root_x = 0
        self.root_y = 0
        self.event_x = 0
        self.event_y = 0
        self.state = 0
        # Set attributes from kwargs, but don't override class-level type
        for k, v in kwargs.items():
            if k != 'type':
                setattr(self, k, v)


class _MockButtonPress(_MockEvent):
    type = 4  # X.ButtonPress


class _MockButtonRelease(_MockEvent):
    type = 5  # X.ButtonRelease


class _MockMotionNotify(_MockEvent):
    type = 6  # X.MotionNotify


@pytest.fixture(autouse=True)
def _mock_xevent_for_tests(monkeypatch):
    """Mock xevent classes to work with fake Display objects in unit tests."""
    import Xlib.protocol.event as xevent_mod
    monkeypatch.setattr(xevent_mod, 'ButtonPress', _MockButtonPress)
    monkeypatch.setattr(xevent_mod, 'ButtonRelease', _MockButtonRelease)
    monkeypatch.setattr(xevent_mod, 'MotionNotify', _MockMotionNotify)


@pytest.fixture(autouse=True)
def _shutdown_multitoon_input_services():
    """Defense in depth: after every test, walk all top-level Qt widgets,
    find any MultitoonTab (anything that owns an `input_service` attribute),
    and call `.shutdown()` on the service so its non-daemon worker thread
    exits and its Xlib MovementKeyGrabber connection is released.

    Without this, tests that construct MultitoonTab leak a non-daemon
    thread that blocks process exit. After enough leaked Python processes
    accumulate, the system's X11 server runs out of client slots and even
    unrelated apps (like the user's real TTMT launching a game) start
    failing with `Xlib.error.DisplayConnectionError: Maximum number of
    clients reached`.

    See: docs/handoff-pynput-x11-client-leak-bug.md
    """
    yield
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for top in app.topLevelWidgets():
        candidates = [top] + top.findChildren(QObject)
        for w in candidates:
            svc = getattr(w, "input_service", None)
            if svc is not None and hasattr(svc, "shutdown"):
                try:
                    svc.shutdown()
                except Exception:
                    pass
    for _ in range(3):
        app.processEvents()
