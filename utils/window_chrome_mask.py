"""Rounded-corner window masking for the opaque-chrome experiment
(TTMT_OPAQUE_MASK_CHROME=1). Lets the frameless window keep real rounded
corners while running OPAQUE (no WA_TranslucentBackground), so macOS can use
its opaque-window compositing fast paths.

NOTE: QRegion edges are integer/logical-pixel based, so corner antialiasing is
rougher than a true alpha corner. Acceptable for the A/B experiment; promotion
to default requires a visual check (see spec section 5).
"""
from __future__ import annotations

from PySide6.QtGui import QPainterPath, QRegion


def rounded_region(width: int, height: int, radius: int) -> QRegion:
    """A rounded-rectangle QRegion for QWidget.setMask(). radius<=0 yields a
    full (square) rectangle."""
    width = max(0, int(width))
    height = max(0, int(height))
    if radius <= 0 or width == 0 or height == 0:
        return QRegion(0, 0, width, height)
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    return QRegion(path.toFillPolygon().toPolygon())
