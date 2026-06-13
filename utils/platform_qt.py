"""Pure decision for the QT_QPA_PLATFORM default. Linux is forced to xcb (or
wayland with the opt-in); macOS/Windows return None (use Qt's native default:
cocoa / windows). Importable everywhere."""
from __future__ import annotations


def qt_platform_for(platform: str, session: str, force_wayland: bool):
    if platform != "linux":
        return None
    if force_wayland and session == "wayland":
        return "wayland"
    return "xcb"
