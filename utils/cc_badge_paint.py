"""CC badge painting primitives.

Pure functions for the CC badge visual treatment:
- complementary_bg_color: derive a circle bg color from the toon's skin.
- paint_cc_badge: render the full badge (added in a later task).

Kept Qt-aware (QColor / QPainter) but widget-free so the math is unit
testable without instantiating widgets.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from utils import cc_race_assets


# bg = (skin hue + 180 deg, skin sat * 0.60, clamp(1 - skin L, 0.18, 0.85)).
# One adaptive-lightness rule for every skin: pale skins get a darker bg,
# dark skins get a lighter bg. The clamp keeps the extremes from inverting
# to pure black or pure white. Achromatic skins use the same formula; their
# near-zero saturation collapses the bg saturation to near-zero, so the bg
# is effectively a neutral grey at the inverted lightness.
_SAT_MULT = 0.60
_L_CLAMP_MIN = 0.18
_L_CLAMP_MAX = 0.85


def complementary_bg_color(skin: QColor) -> QColor:
    """Return the badge background color for a given skin color.

    One adaptive-lightness rule: complement hue, sat * 0.60, L clamped to
    the opposite end of the lightness axis from the skin. Pale skins get a
    darker bg; dark skins get a lighter bg. Achromatic skins inherit the
    same rule (their near-zero saturation collapses the bg saturation).
    """
    h, s, l, _ = skin.getHslF()
    # QColor.getHslF returns hue = -1 for achromatic colors. Normalize.
    if h < 0:
        h = 0.0

    new_h = (h + 0.5) % 1.0  # +180 degrees in [0,1] space
    new_s = s * _SAT_MULT
    new_l = max(_L_CLAMP_MIN, min(_L_CLAMP_MAX, 1.0 - l))
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
) -> None:
    """Paint a CC badge: complement bg circle, then either the race
    silhouette in skin color or a slot-number fallback.

    Caller controls hover/pencil rendering separately (see pencil_rect_for).
    """
    painter.setRenderHint(QPainter.Antialiasing)
    bg = complementary_bg_color(skin)

    # Background circle
    painter.setPen(Qt.NoPen)
    painter.setBrush(bg)
    painter.drawEllipse(rect)

    if asset_stem is not None and _paint_silhouette(painter, rect, skin, asset_stem):
        return

    # Fallback: slot number in white. Bg stays the complement so the badge
    # still feels CC-mode-styled even without a silhouette.
    _paint_slot_number(painter, rect, slot_number)
