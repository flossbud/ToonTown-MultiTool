"""CC badge painting primitives.

Pure functions for the CC badge visual treatment:
- complementary_bg_color: derive a circle bg color from the toon's skin.
- paint_cc_badge: render the full badge (added in a later task).

Kept Qt-aware (QColor / QPainter) but widget-free so the math is unit
testable without instantiating widgets.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPixmap

from utils import cc_race_assets


# bg = (skin hue + 180 deg, skin sat * 0.60, adaptive-lightness):
#   - Naive case: clamp(1 - skin L, 0.18, 0.85). Pale skins get a darker
#     bg, dark skins get a lighter bg.
#   - Mid-L case (|1 - 2L| < _MIN_L_DELTA, i.e. skin L approx in [0.35,
#     0.65]): the naive inversion lands too close to the skin lightness,
#     so the silhouette would vanish into the bg. Instead, push bg L to
#     whichever clamp endpoint is furthest from the skin L.
# Achromatic skins follow the same rule; their near-zero saturation
# collapses the bg saturation, so the bg is effectively a neutral grey
# at the chosen lightness.
_SAT_MULT = 0.60
_L_CLAMP_MIN = 0.18
_L_CLAMP_MAX = 0.85
_MIN_L_DELTA = 0.30  # naive inversion must differ from skin L by at least this


def complementary_bg_color(skin: QColor) -> QColor:
    """Return the badge background color for a given skin color.

    Naive rule: complement hue, sat * 0.60, L = clamp(1 - skin L,
    _L_CLAMP_MIN, _L_CLAMP_MAX). Pale skins get a darker bg, dark skins
    get a lighter bg.

    Mid-L skins (L approx 0.5) would have a naive bg L approx 0.5 too,
    losing the silhouette in the background. The mid-L branch detects
    this case (`abs(1 - L - L) < _MIN_L_DELTA`) and pushes bg L to
    whichever clamp endpoint is furthest from the skin L, restoring
    luminance contrast.

    Achromatic skins follow the same rule; their near-zero saturation
    collapses the bg saturation.
    """
    h, s, l, _ = skin.getHslF()
    # QColor.getHslF returns hue = -1 for achromatic colors. Normalize.
    if h < 0:
        h = 0.0

    new_h = (h + 0.5) % 1.0  # +180 degrees in [0,1] space
    new_s = s * _SAT_MULT

    inverted_l = 1.0 - l
    if abs(inverted_l - l) < _MIN_L_DELTA:
        # Mid-L case: pick the clamp endpoint furthest from skin L.
        new_l = (
            _L_CLAMP_MIN
            if (l - _L_CLAMP_MIN) > (_L_CLAMP_MAX - l)
            else _L_CLAMP_MAX
        )
    else:
        new_l = max(_L_CLAMP_MIN, min(_L_CLAMP_MAX, inverted_l))

    return QColor.fromHslF(new_h, new_s, new_l)


# ---------------------------------------------------------------------------
# Pencil overlay sizing constants
# ---------------------------------------------------------------------------

# Pencil overlay sizing rule: 25% of badge width, clamped to [14, 28] px.
_PENCIL_RATIO = 0.25
_PENCIL_MIN = 14
_PENCIL_MAX = 28
_PENCIL_INSET = 4  # px from badge bottom-left edge


def pencil_rect_for(badge_rect: QRect) -> QRect:
    """Return the pencil overlay rect (bottom-left of the badge)."""
    diameter = round(badge_rect.width() * _PENCIL_RATIO)
    diameter = max(_PENCIL_MIN, min(_PENCIL_MAX, diameter))
    x = badge_rect.left() + _PENCIL_INSET
    y = badge_rect.bottom() - _PENCIL_INSET - diameter + 1
    return QRect(x, y, diameter, diameter)


def _paint_silhouette(
    painter: QPainter, rect: QRect, skin: QColor, stem: str
) -> bool:
    """Paint the head silhouette in `skin`, masked by the race PNG.
    Returns True if the silhouette was painted (asset found and loaded)."""
    pm = cc_race_assets.load_race_pixmap(stem)
    if pm is None or pm.isNull():
        return False

    inset = round(rect.width() * 0.10)
    target = rect.adjusted(inset, inset, -inset, -inset)

    # Use the PNG as an alpha mask: paint skin color, then composite the
    # mask so only the mask's opaque pixels survive.
    tmp = QPixmap(target.size())
    tmp.fill(Qt.transparent)
    tp = QPainter(tmp)
    tp.setRenderHint(QPainter.Antialiasing)
    tp.setRenderHint(QPainter.SmoothPixmapTransform)
    tp.fillRect(tmp.rect(), skin)
    tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    scaled = pm.scaled(
        target.size(),
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    # Center the scaled pixmap within the tmp surface.
    dx = (tmp.width() - scaled.width()) // 2
    dy = (tmp.height() - scaled.height()) // 2
    tp.drawPixmap(dx, dy, scaled)
    tp.end()

    painter.drawPixmap(target, tmp)
    return True


def _paint_slot_number(
    painter: QPainter, rect: QRect, slot_number: int
) -> None:
    """Fallback paint: white slot number centered in the circle."""
    painter.setPen(Qt.white)
    f: QFont = painter.font()
    f.setPixelSize(max(12, round(rect.width() * 0.45)))
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(rect, Qt.AlignCenter, str(slot_number))


def paint_cc_badge(
    painter: QPainter,
    rect: QRect,
    skin: QColor,
    asset_stem: Optional[str],
    slot_number: int,
    *,
    portrait_brush: Optional[QBrush] = None,
    pattern: Optional[tuple[str, QColor]] = None,
    circle_outline: Optional[tuple[QColor, int]] = None,
) -> None:
    """Paint a CC badge: bg circle (skin-complement or override), optional
    pattern overlay, then either the race silhouette in skin color or a
    slot-number fallback, and finally an optional circle outline on top.

    `portrait_brush` overrides the bg fill. When None, fall back to the
    historical complement-of-skin color.
    `pattern` is an optional (name, color) tuple; when present, the
    tinted pattern tile is tiled inside the inner circle, beneath the
    silhouette.
    `circle_outline` is an optional (QColor, width_px) tuple; when present,
    a ring of that color and width is drawn last, on top of the silhouette
    and pattern.
    """
    painter.setRenderHint(QPainter.Antialiasing)

    inner = rect.adjusted(2, 2, -2, -2)

    bg_brush = portrait_brush if portrait_brush is not None else QBrush(
        complementary_bg_color(skin)
    )
    painter.setPen(Qt.NoPen)
    painter.setBrush(bg_brush)
    painter.drawEllipse(inner)

    if pattern is not None:
        from utils.toon_pattern_assets import tinted_pattern_pixmap
        name, color = pattern
        pm = tinted_pattern_pixmap(name, color, tile_size=24)
        if not pm.isNull():
            path = QPainterPath()
            path.addEllipse(inner)
            painter.save()
            painter.setClipPath(path)
            for y in range(inner.top(), inner.bottom() + 1, 24):
                for x in range(inner.left(), inner.right() + 1, 24):
                    painter.drawPixmap(x, y, pm)
            painter.restore()

    if asset_stem is not None and _paint_silhouette(painter, inner, skin, asset_stem):
        pass  # silhouette painted
    else:
        _paint_slot_number(painter, inner, slot_number)

    # Circle outline (drawn last, on top of silhouette and pattern).
    if circle_outline is not None:
        from PySide6.QtGui import QPen
        color, width = circle_outline
        inset = max(0, width // 2)
        painter.setPen(QPen(color, width))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(inner.adjusted(inset, inset, -inset, -inset))
