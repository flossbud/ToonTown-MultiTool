"""Pure pixmap effects for the toon portrait paint pipeline.

`build_silhouette_outline_pixmap` returns a donut-shaped colored halo
around the input alpha (interior left transparent). `build_silhouette_shadow_pixmap`
returns a softly-blurred colored shadow of the input alpha. Both are
called from paintEvent and are designed to be cheap on 96-128 px
sources; callers should cache results keyed on (source, params)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPixmap,
)


_RING_DIRECTIONS = (
    (-1, -1), (0, -1), (1, -1),
    (-1,  0),          (1,  0),
    (-1,  1), (0,  1), (1,  1),
)


def build_silhouette_outline_pixmap(
    pose_pm: QPixmap, color: QColor, width: int,
) -> QPixmap:
    """Returns a pixmap the same size as `pose_pm` with a colored halo
    around the source's alpha edge. Interior of the source shape is
    transparent (donut), so the caller can draw `pose_pm` over the
    result without the outline bleeding through opaque pose pixels.

    Implementation: paint pose `pose_pm` 8 times offset by `width` px
    in each compass direction onto a fresh transparent QPixmap. The
    union is the dilated alpha shape. Mask with the outline color via
    CompositionMode_SourceIn, then punch out the original alpha via
    CompositionMode_DestinationOut. Good fidelity for widths 1-3 px."""
    if width <= 0 or pose_pm.isNull():
        out = QPixmap(pose_pm.size())
        out.fill(Qt.transparent)
        return out

    out = QPixmap(pose_pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    # Dilation pass: paint source 8 times around a ring of `width` px.
    for dx, dy in _RING_DIRECTIONS:
        p.drawPixmap(dx * width, dy * width, pose_pm)
    # Color the dilated shape.
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), color)
    # Punch out the original alpha so only the halo remains.
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    p.drawPixmap(0, 0, pose_pm)
    p.end()
    return out
