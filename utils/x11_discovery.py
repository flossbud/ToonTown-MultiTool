"""X11 window discovery via python-Xlib.

Replaces the xdotool subprocess calls (`search --class`, `getactivewindow`,
`getwindowgeometry`, `getwindowpid`) used by the window manager and the TTR
API client. xdotool was bundled in the Flatpak manifest but was never bundled
in the AppImage, which made multitooning silently fail on hosts that don't
ship xdotool by default (notably Fedora). python-Xlib is already a Linux
dependency for the input backend and XRes PID resolution, so this is a
dependency removal, not addition.

All helpers open a fresh Xlib display per call and close it before returning.
That matches the per-call cost of the xdotool subprocesses they replace and
sidesteps thread-safety questions about sharing a Display across the polling
threads.
"""

from __future__ import annotations

import sys


def _open_display():
    """Return a connected Xlib Display or None on failure.

    Centralized so platform/import guards live in one place; callers always
    get either a usable Display or None, never an exception.
    """
    if sys.platform == "win32":
        return None
    try:
        from Xlib import display as xdisplay  # type: ignore
        return xdisplay.Display()
    except Exception:
        return None


def find_window_ids_by_class(class_names: list[str]) -> list[str]:
    """Return X11 window IDs whose WM_CLASS class component contains any of
    ``class_names``. Substring match, case-sensitive, mirroring the behavior
    of ``xdotool search --class``.

    Returns window IDs as decimal strings (matching xdotool's output format
    so downstream code doesn't have to change representation).
    """
    if not class_names:
        return []
    d = _open_display()
    if d is None:
        return []
    try:
        results: list[str] = []
        targets = tuple(class_names)
        try:
            root = d.screen().root
        except Exception:
            return []
        _walk_collect(root, targets, results)
        return results
    finally:
        try:
            d.close()
        except Exception:
            pass


def _walk_collect(window, targets: tuple[str, ...], results: list[str]) -> None:
    try:
        wm_class = window.get_wm_class()
    except Exception:
        wm_class = None
    if wm_class and len(wm_class) >= 2:
        cls = wm_class[1] or ""
        if any(target in cls for target in targets):
            results.append(str(window.id))
    try:
        children = window.query_tree().children
    except Exception:
        children = []
    for child in children:
        _walk_collect(child, targets, results)


def get_window_root_x(wid: str) -> int | None:
    """Return the window's top-left X coordinate in root-window space.

    This is the value xdotool prints as ``Position:`` and what we use to
    sort toon windows left-to-right.
    """
    d = _open_display()
    if d is None:
        return None
    try:
        try:
            win = d.create_resource_object("window", int(wid))
            coords = win.translate_coords(d.screen().root, 0, 0)
            return int(coords.x)
        except Exception:
            return None
    finally:
        try:
            d.close()
        except Exception:
            pass


def get_active_window_id() -> str | None:
    """Read ``_NET_ACTIVE_WINDOW`` from the root window. Returns the active
    window ID as a decimal string, or None on Wayland-only sessions / when
    the property is missing.
    """
    d = _open_display()
    if d is None:
        return None
    try:
        try:
            root = d.screen().root
            atom = d.intern_atom("_NET_ACTIVE_WINDOW")
            from Xlib import X  # type: ignore
            prop = root.get_full_property(atom, X.AnyPropertyType)
            if prop and prop.value:
                return str(int(prop.value[0]))
        except Exception:
            return None
    finally:
        try:
            d.close()
        except Exception:
            pass
    return None


def get_window_pid(wid: str) -> int | None:
    """Read ``_NET_WM_PID`` from the window. Returns the PID as set by the
    window's owner (this is a namespace PID inside a Flatpak game install;
    callers who need the host PID should prefer the XRes path instead).
    """
    d = _open_display()
    if d is None:
        return None
    try:
        try:
            win = d.create_resource_object("window", int(wid))
            atom = d.intern_atom("_NET_WM_PID")
            from Xlib import X  # type: ignore
            prop = win.get_full_property(atom, X.AnyPropertyType)
            if prop and prop.value:
                return int(prop.value[0])
        except Exception:
            return None
    finally:
        try:
            d.close()
        except Exception:
            pass
    return None
