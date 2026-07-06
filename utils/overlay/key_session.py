"""Chord-capture keyboard sessions for unfocusable overlay surfaces.

Overlay surfaces are top-level windows with Qt.WindowDoesNotAcceptFocus,
which on cocoa means canBecomeKeyWindow == NO: the window server never
delivers them a single keyboard event, so a ChordCaptureButton hosted in
the floating settings panel is deaf by construction (live 2026-07-05:
every key beeped off the still-key app; Qt's grabKeyboard only redirects
events already delivered to the app). X11 does not have this failure -
grabKeyboard there is a real active grab that seizes the keyboard
regardless of focus - and win32 panels still take keyboard focus.

begin()/end() bracket one capture: on cocoa the surface temporarily
becomes the key window via the backend's Spotlight-pattern session
(nonactivating panels may take key status without activating the app);
everywhere else, and for normally-focusable windows (the main window's
Settings tab), both calls are no-ops.

TTMT_NO_KEY_SESSION=1 disables the cocoa session (capture in the float
panel reverts to deaf) in case the key-window handoff misbehaves live.
"""
from __future__ import annotations

import os

from utils.overlay.backend import overlay_trace

_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        from utils.overlay.backend import get_overlay_backend
        _backend = get_overlay_backend()
    return _backend


def _session_window(widget):
    """The widget's top-level window IF it needs a key session (an
    unfocusable overlay surface); None for normal windows."""
    try:
        from PySide6.QtCore import Qt
        w = widget.window()
        if w is None or not (w.windowFlags() & Qt.WindowDoesNotAcceptFocus):
            return None
        return w
    except Exception:
        return None


def begin(widget) -> bool:
    """Start a keyboard session for the capture widget's window. Returns
    whether a session was actually established (False also covers "not
    needed" - a focusable window receives keys on its own)."""
    if os.environ.get("TTMT_NO_KEY_SESSION"):
        overlay_trace("key-session: disabled (TTMT_NO_KEY_SESSION)")
        return False
    w = _session_window(widget)
    if w is None:
        return False
    backend = _get_backend()
    begin_fn = getattr(backend, "begin_key_session", None)
    if begin_fn is None:
        return False
    try:
        return bool(begin_fn(w))
    except Exception:
        return False


def end(widget) -> None:
    w = _session_window(widget)
    if w is None:
        return
    backend = _get_backend()
    end_fn = getattr(backend, "end_key_session", None)
    if end_fn is None:
        return
    try:
        end_fn(w)
    except Exception:
        pass
