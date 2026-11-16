"""X11 without a compositing manager: strips as shaped windows.

A translucent window needs a compositor to blend it. Without one the
transparent parts come out black and window opacity does nothing. The
fallback is the X Shape extension: the window's BOUNDING shape is set to
exactly what is painted (the blocks, an open card), so the rest of the
window does not exist on screen; an empty shape hides it.

A compositing manager announces itself by owning the _NET_WM_CM_S<screen>
selection. Everything here is best effort on a connection of its own, GUI
thread only; any failure reports "composited" so the normal path is used.
"""
from __future__ import annotations

_display = None


def _get_display():
    global _display
    if _display is None:
        from Xlib import display as xdisplay
        d = xdisplay.Display()
        d.set_error_handler(lambda *_: None)
        _display = d
    return _display


def _drop_display() -> None:
    global _display
    d, _display = _display, None
    if d is not None:
        try:
            d.close()
        except Exception:
            pass


def composited() -> bool:
    """True when a compositing manager is running (or cannot be asked)."""
    try:
        from Xlib import X
        d = _get_display()
        atom = d.intern_atom(f"_NET_WM_CM_S{d.get_default_screen()}")
        return d.get_selection_owner(atom) != X.NONE
    except Exception:
        _drop_display()
        return True


def set_bounding(wid: int, rects) -> bool:
    """Make the window exist only inside `rects` ((x, y, w, h) in device px,
    window-local). An empty list leaves nothing on screen."""
    try:
        from Xlib import X
        from Xlib.ext import shape
        d = _get_display()
        win = d.create_resource_object("window", int(wid))
        win.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.Unsorted, 0, 0,
                             [tuple(int(v) for v in r) for r in rects])
        d.flush()
        return True
    except Exception:
        _drop_display()
        return False


def clear_bounding(wid: int) -> bool:
    """Back to the whole window (a compositor appeared)."""
    try:
        from Xlib import X
        from Xlib.ext import shape
        d = _get_display()
        win = d.create_resource_object("window", int(wid))
        win.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, X.NONE)
        d.flush()
        return True
    except Exception:
        _drop_display()
        return False
