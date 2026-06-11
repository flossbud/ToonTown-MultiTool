"""Win32 window discovery for click sync: client-area geometry and a
stacking-aware point hit test. Mirrors utils/x11_discovery's contracts
(geometry tuple semantics, tri-state hit test) so the service and tab
wiring stay platform-agnostic.

win32 APIs are imported lazily INSIDE functions: the module must import
cleanly on every platform (main.py --self-check sweeps all modules, and
the Linux CI unit tests patch sys.modules with fakes).
"""
from __future__ import annotations


def _get_ancestor_root(hwnd: int) -> int:
    """GetAncestor(GA_ROOT): the toplevel for any (child) hwnd. ctypes
    rather than win32gui — present in every pywin32/ctypes combination."""
    import ctypes
    return int(ctypes.windll.user32.GetAncestor(hwnd, 2))  # GA_ROOT = 2


def get_window_geometry(wid: str) -> tuple[int, int, int, int] | None:
    """(screen_x, screen_y, width, height) of the CLIENT area, physical
    pixels (the app is per-monitor DPI aware via Qt). None on any failure
    (dead hwnd, malformed wid, win32 error) — same contract as
    x11_discovery.get_window_geometry."""
    try:
        import win32gui
        hwnd = int(wid)
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        x, y = win32gui.ClientToScreen(hwnd, (0, 0))
        return (int(x), int(y), int(right - left), int(bottom - top))
    except Exception:
        return None


def toplevel_at_point(root_x: int, root_y: int) -> str | None:
    """Tri-state, same contract as x11_discovery.toplevel_at_point:
    a toplevel hwnd string when a window contains the point; "" (empty)
    when the lookup SUCCEEDED but nothing is there; None only on lookup
    FAILURE. WindowFromPoint returns the deepest child under the point;
    GA_ROOT normalizes to the toplevel, which is what the window manager
    tracks (EnumWindows hwnds), so callers compare directly — no
    frame-vs-client ancestor walk exists on Windows."""
    try:
        import win32gui
        hwnd = win32gui.WindowFromPoint((int(root_x), int(root_y)))
        if not hwnd:
            return ""
        root = _get_ancestor_root(int(hwnd))
        return str(root or int(hwnd))
    except Exception:
        return None
