import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Stub out win32 modules for Linux test runs; the win32_backend module
# imports them in try/except, but VK_MAP uses win32con at module level.
if 'win32con' not in sys.modules:
    _stub_win32con = types.SimpleNamespace(
        VK_SPACE=0x20, VK_RETURN=0x0D, VK_BACK=0x08, VK_TAB=0x09,
        VK_ESCAPE=0x1B, VK_DELETE=0x2E, VK_UP=0x26, VK_DOWN=0x28,
        VK_LEFT=0x25, VK_RIGHT=0x27, VK_HOME=0x24, VK_END=0x23,
        VK_PRIOR=0x21, VK_NEXT=0x22, VK_INSERT=0x2D,
        VK_F1=0x70, VK_F2=0x71, VK_F3=0x72, VK_F4=0x73, VK_F5=0x74,
        VK_F6=0x75, VK_F7=0x76, VK_F8=0x77, VK_F9=0x78, VK_F10=0x79,
        VK_F11=0x7A, VK_F12=0x7B,
        VK_NUMPAD0=0x60, VK_NUMPAD1=0x61, VK_NUMPAD2=0x62, VK_NUMPAD3=0x63,
        VK_NUMPAD4=0x64, VK_NUMPAD5=0x65, VK_NUMPAD6=0x66, VK_NUMPAD7=0x67,
        VK_NUMPAD8=0x68, VK_NUMPAD9=0x69,
        VK_DECIMAL=0x6E, VK_ADD=0x6B, VK_SUBTRACT=0x6D,
        VK_MULTIPLY=0x6A, VK_DIVIDE=0x6F,
        WM_KEYDOWN=0x0100, WM_KEYUP=0x0101,
    )
    sys.modules['win32con'] = _stub_win32con

if 'win32gui' not in sys.modules:
    sys.modules['win32gui'] = types.SimpleNamespace()

if 'win32api' not in sys.modules:
    sys.modules['win32api'] = types.SimpleNamespace()

if 'win32process' not in sys.modules:
    sys.modules['win32process'] = types.SimpleNamespace()


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
