"""Map screen points between native (physical) and Qt logical coordinate space.

The click-sync service emits NATIVE pixels (capture, geometry, and injection all
run in OS coordinates); Qt widget geometry (`QWidget.move`, `geometry()`) is in
LOGICAL coordinates. These helpers are the single conversion point, shared by the
ghost-cursor renderer and the transparent-overlay controller. Pure: screens are
injected for testing and default to the live QGuiApplication screens.
"""
from __future__ import annotations

import sys


def native_to_logical(x, y, screens=None):
    """Map a native (physical) screen point into Qt's logical coordinate space.

    Qt scales each screen around a fixed origin - the screen's top-left is
    numerically identical in both spaces and sizes divide by devicePixelRatio -
    so the containing screen is the one whose half-open native rect (origin,
    logical size * dpr) holds the point, and logical = origin + (native - origin)
    / dpr. At DPR 1 this is the identity. A point inside no screen (transient
    geometry race) maps via the first screen rather than dropping the event."""
    if screens is None:
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
    target = None
    for s in screens:
        g = s.geometry()
        dpr = s.devicePixelRatio()
        if (g.x() <= x < g.x() + g.width() * dpr
                and g.y() <= y < g.y() + g.height() * dpr):
            target = s
            break
    if target is None:
        if not screens:
            return int(x), int(y)
        target = screens[0]
    g = target.geometry()
    dpr = target.devicePixelRatio()
    return (round(g.x() + (x - g.x()) / dpr),
            round(g.y() + (y - g.y()) / dpr))


def emitted_to_logical(x, y, screens=None):
    """Map the click-sync service's emitted point into Qt's logical space.

    On macOS the service emits LOGICAL POINTS, so the mapping is the identity
    (negative multi-display coords preserved). Everywhere else it emits physical
    pixels, so delegate to native_to_logical (which divides by devicePixelRatio).
    """
    if sys.platform == "darwin":
        return (int(x), int(y))
    return native_to_logical(x, y, screens)
