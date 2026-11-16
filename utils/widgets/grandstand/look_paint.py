"""The one disc painter of the Appearance editor (handoff §4.2).

The framing canvas, the eight Look swatches and the small portraits are the
same disc at different sizes: backdrop, pattern, the toon, the accent ring.
Each is painted from a stored-look *entry* through the
`utils.toon_customization_resolve` rules, the way production's badge is, so
what the editor shows is what a Save will make the rest of the app draw.

Colours arrive from the caller (the entry, or `palette.py` for fallbacks);
this module holds none.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

import utils.portrait_effects as portrait_effects
from utils.toon_customization_resolve import (
    resolve_accent, resolve_portrait_brush, resolve_portrait_pattern,
    resolve_portrait_transform, resolve_silhouette_outline,
    resolve_silhouette_shadow,
)
from utils.toon_pattern_assets import tinted_pattern_pixmap

# Production tiles a 24 px pattern over the Multitoon badge (172 px at the
# compact card's native size). The editor's discs keep that ratio, so a
# pattern is as coarse on the 240 px canvas as it is where it will be seen,
# and still reads as a pattern on a 50 px Look swatch.
PATTERN_TILE = 24
PATTERN_REFERENCE_DISC = 172
MIN_PATTERN_TILE = 6

# Species art is inset wherever a circular mask is involved, so ears and
# bills stay clear of it (handoff §7, ART_INSET).
ART_INSET = 0.8

# A `head` render in a small disc: the reference build's Look swatches.
HEAD_SCALE = 1.06
HEAD_SHIFT = 0.06

_EFFECTS_CACHE_MAX = 6
_effects_cache: "OrderedDict[tuple, tuple]" = OrderedDict()


def pattern_tile_for(diameter: float) -> int:
    return max(MIN_PATTERN_TILE,
               round(PATTERN_TILE * diameter / PATTERN_REFERENCE_DISC))


def _safe_transform(entry: dict) -> tuple[float, float, float, float]:
    try:
        return resolve_portrait_transform(entry)
    except (TypeError, ValueError):
        return (1.0, 0.0, 0.0, 0.0)


def _silhouette_effects(art: QPixmap, scaled: QPixmap, entry: dict) -> tuple:
    """(outline pixmap | None, shadow pixmap | None, dx, dy) for a stored
    silhouette outline / shadow. The editor has no control for either, but a
    look that carries one must not preview without it."""
    outline = resolve_silhouette_outline(entry)
    shadow = resolve_silhouette_shadow(entry)
    if outline is None and shadow is None:
        return (None, None, 0, 0)
    key = (art.cacheKey(), scaled.width(), scaled.height(),
           outline[0].name() if outline else None, outline[1] if outline else 0,
           shadow[0].name() if shadow else None, shadow[1] if shadow else 0)
    hit = _effects_cache.get(key)
    if hit is None:
        outline_pm = (portrait_effects.build_silhouette_outline_pixmap(
            scaled, outline[0], outline[1]) if outline else None)
        shadow_pm = (portrait_effects.build_silhouette_shadow_pixmap(
            scaled, shadow[0], shadow[1]) if shadow else None)
        hit = (outline_pm, shadow_pm)
        _effects_cache[key] = hit
        while len(_effects_cache) > _EFFECTS_CACHE_MAX:
            _effects_cache.popitem(last=False)
    else:
        _effects_cache.move_to_end(key)
    dx, dy = (shadow[2], shadow[3]) if shadow else (0, 0)
    return (hit[0], hit[1], dx, dy)


def paint_look_disc(painter: QPainter, rect: QRectF, entry: dict, *,
                    fill_fallback: QColor, accent_fallback: QColor,
                    ring_width: float, art: Optional[QPixmap] = None,
                    art_scale: float = 1.0, art_shift: float = 0.0,
                    framed: bool = False) -> None:
    """Paint one look into the circle inscribed in `rect`.

    `art` is the toon's render or its race icon, drawn `art_scale` times the
    diameter and shifted down by `art_shift` of it. With `framed`, the
    entry's stored transform is applied exactly as production's badge
    applies it (rotate about the centre, then an offset in zoomed circle
    fractions, with the zoom baked into the one downscale)."""
    rect = QRectF(rect)
    diameter = min(rect.width(), rect.height())
    if diameter <= 0:
        return
    entry = entry if isinstance(entry, dict) else {}
    clip = QPainterPath()
    clip.addEllipse(rect)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(resolve_portrait_brush(entry, fill_fallback))
    painter.drawEllipse(rect)

    painter.setClipPath(clip, Qt.IntersectClip)
    pattern = resolve_portrait_pattern(entry)
    if pattern is not None:
        name, color = pattern
        tile = pattern_tile_for(diameter)
        pm = tinted_pattern_pixmap(name, color, tile_size=tile)
        if not pm.isNull():
            top, left = int(rect.top()), int(rect.left())
            for y in range(top, int(rect.bottom()) + 1, tile):
                for x in range(left, int(rect.right()) + 1, tile):
                    painter.drawPixmap(x, y, pm)

    if art is not None and not art.isNull():
        zoom, off_x, off_y, rotate = (
            _safe_transform(entry) if framed else (1.0, 0.0, 0.0, 0.0))
        target = max(1, round(diameter * art_scale * zoom))
        scaled = art.scaled(QSize(target, target), Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
        painter.translate(rect.center())
        painter.rotate(rotate)
        painter.translate(QPointF(int(off_x * diameter) * zoom,
                                  int(off_y * diameter) * zoom
                                  + art_shift * diameter))
        x, y = -scaled.width() // 2, -scaled.height() // 2
        if framed:
            outline_pm, shadow_pm, dx, dy = _silhouette_effects(art, scaled, entry)
            if shadow_pm is not None and not shadow_pm.isNull():
                pad_x = (shadow_pm.width() - scaled.width()) // 2
                pad_y = (shadow_pm.height() - scaled.height()) // 2
                painter.drawPixmap(x - pad_x + dx, y - pad_y + dy, shadow_pm)
            if outline_pm is not None and not outline_pm.isNull():
                painter.drawPixmap(x, y, outline_pm)
        painter.drawPixmap(x, y, scaled)
    painter.restore()

    if ring_width > 0:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(resolve_accent(entry, accent_fallback), ring_width))
        half = ring_width / 2.0
        painter.drawEllipse(rect.adjusted(half, half, -half, -half))
        painter.restore()
