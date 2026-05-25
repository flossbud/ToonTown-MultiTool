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
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
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


def build_silhouette_shadow_pixmap(
    pose_pm: QPixmap, color: QColor, blur_px: int,
) -> QPixmap:
    """Returns a softly-blurred colored shadow of `pose_pm`'s alpha.

    Implementation: wrap pose in a QGraphicsPixmapItem, attach a
    QGraphicsDropShadowEffect with the requested color and blur, render
    the resulting bounding rect (including blur padding) onto a fresh
    transparent QPixmap. Output size is `pose_pm.size()` plus 2 * blur_px
    on each axis so the soft edge isn't clipped."""
    pad = max(0, blur_px)
    out_w = pose_pm.width() + 2 * pad
    out_h = pose_pm.height() + 2 * pad
    out = QPixmap(out_w, out_h)
    out.fill(Qt.transparent)

    if pose_pm.isNull() or out_w == 0 or out_h == 0:
        return out

    # Build a solid-color version of the source (preserve alpha, replace RGB
    # with shadow color). The scene item uses this so both the body and the
    # blurred halo share the requested color.
    colored = QPixmap(pose_pm.size())
    colored.fill(Qt.transparent)
    cp = QPainter(colored)
    cp.drawPixmap(0, 0, pose_pm)
    cp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    cp.fillRect(colored.rect(), color)
    cp.end()

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(colored)
    effect = QGraphicsDropShadowEffect()
    effect.setColor(color)
    effect.setBlurRadius(blur_px)
    effect.setOffset(0, 0)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    # Source is positioned at (pad, pad) in output coords.
    source_rect = item.boundingRect()
    target_rect = source_rect.translated(pad, pad)
    scene.render(p, target_rect, source_rect)
    p.end()
    return out
