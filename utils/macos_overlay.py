"""macOS NSWindow hardening for the ghost-cursor overlays.

Applies the floating-overlay recipe proven by the Phase-0 spike
(`scripts/macos_ghost_overlay_spike.py`, operator-validated 2026-06-15 against
two live TTR toons): a Qt overlay floats above a BACKGROUND game window and stays
click-through. Lazy PyObjC; never raises; only ever touches the real cocoa
backend (under any other QPA, `winId()` is not an NSView and messaging it would
segfault - see memory project_qt_winid_objc_offscreen_segv).
"""
from __future__ import annotations

import sys

_logged_reasons: set[str] = set()


def _once(reason: str) -> tuple[bool, str]:
    """Log a failure reason at most once, return the (False, reason) result."""
    if reason not in _logged_reasons:
        _logged_reasons.add(reason)
        print(f"[macos_overlay] hardening unavailable: {reason}")
    return (False, reason)


def harden_overlay_window(widget) -> tuple[bool, str | None]:
    """Apply the proven floating-overlay NSWindow recipe to a realized Qt widget.

    Recipe (spike winner): NSFloatingWindowLevel so it floats above a backgrounded
    app's window; collectionBehavior canJoinAllSpaces|stationary; ignoresMouseEvents
    so a click passes straight through to the toon. The NSWindow is resolved FRESH
    from `winId()` on every call (never caches a wrapped objc ref across native
    surface recreation). Never raises. Returns (ok, reason|None).

    Acts only on the real cocoa QPA; returns (False, reason) everywhere else so the
    caller can fail closed without risking the winId->objc segfault class.
    """
    if sys.platform != "darwin":
        return (False, "not darwin")
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "cocoa":
            return (False, "not cocoa")
    except Exception as e:
        return (False, f"platform check failed: {e}")
    try:
        import objc
        import AppKit
    except Exception as e:
        return _once(f"PyObjC unavailable: {e}")
    try:
        view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window()
    except Exception as e:
        return _once(f"NSWindow resolve failed: {e}")
    if window is None:
        return (False, "NSWindow not realized yet")
    try:
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary)
        window.setIgnoresMouseEvents_(True)
        if window.isKindOfClass_(AppKit.NSPanel):
            # A Qt.Tool window can be realized as an NSPanel, which hides when the
            # app deactivates; keep the ghost visible while a toon is frontmost.
            window.setHidesOnDeactivate_(False)
    except Exception as e:
        return _once(f"recipe apply failed: {e}")
    return (True, None)
