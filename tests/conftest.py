import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


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
