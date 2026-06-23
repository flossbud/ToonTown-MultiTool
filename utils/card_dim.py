"""The card idle/inactive dim filter: luma-preserving saturate(0.45)*brightness(0.75).

This is the single source of truth for the Multitoon card dim (design idle state,
screenshot 02-idle.png). It mixes each channel toward the pixel's OWN luma (not a
fixed mid-grey, which is what made the old flat wash look milky), then darkens.

Pure painting / QImage only - no QGraphicsEffect - so it is safe inside the
QGraphicsProxyWidget used by transparent-overlay mode.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QImage, QPixmap

SAT = 0.45      # saturate(0.45): fraction of original chroma kept
BRIGHT = 0.75   # brightness(0.75): uniform darken


def dim_color(c: QColor) -> QColor:
    """Apply saturate(SAT) then brightness(BRIGHT) to a single colour, luma-
    preserving (Rec.601 weights, matching _build_grey and PIL's ImageEnhance.Color).
    Alpha is preserved."""
    lum = 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()

    def ch(v: int) -> int:
        return max(0, min(255, round((v * SAT + lum * (1.0 - SAT)) * BRIGHT)))

    return QColor(ch(c.red()), ch(c.green()), ch(c.blue()), c.alpha())


def dim_pixmap(pm: QPixmap) -> QPixmap:
    """Return a dimmed copy of `pm` (dim_color per opaque pixel; fully-transparent
    pixels untouched). Caller MUST cache the result - this is a per-pixel pass and
    is only acceptable on static (inactive) content."""
    if pm.isNull():
        return pm
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            img.setPixelColor(x, y, dim_color(c))
    return QPixmap.fromImage(img)
