import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


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
    # Deterministically destroy any lingering top-level widget trees while the
    # GIL is held. A built MultiToonTool window holds QGraphicsScene-backed
    # effects (glow / blur) deep in its tree; if those survive to the
    # interpreter's final GC, Python frees their Shiboken wrappers in a racy
    # order against Qt's C++ destruction, double-freeing the scene and crashing
    # the process with SIGSEGV (pytest then exits 139 even though every test
    # passed). Closing + deleteLater + draining the event loop here destroys the
    # C++ objects now, so the wrappers are already invalidated at exit.
    for top in list(app.topLevelWidgets()):
        try:
            top.close()
            top.deleteLater()
        except Exception:
            pass
    for _ in range(5):
        app.processEvents()


@pytest.fixture(autouse=True)
def _no_real_hotkey_grabs(monkeypatch):
    """Full-window tests must never install real X root grabs (F5, Ctrl+1..5)
    on the developer's live session; provider behavior is unit-tested against
    fakes in tests/test_global_hotkeys_x11.py."""
    try:
        from services.global_hotkeys import X11GlobalHotkeys
    except Exception:
        return
    monkeypatch.setattr(X11GlobalHotkeys, "start", lambda self: False)
