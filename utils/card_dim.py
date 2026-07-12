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
DIM_FADE_MS = 200   # lit -> dim fade duration; paired with QEasingCurve.OutCubic


def dim_color(c: QColor, sat: float = SAT, bright: float = BRIGHT) -> QColor:
    """Apply saturate(sat) then brightness(bright), luma-preserving (Rec.601
    weights, matching _build_grey and PIL's ImageEnhance.Color). Defaults are
    the historic dark-theme filter; the light palette passes (0.35, 1.0).
    Alpha is preserved."""
    lum = 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()

    def ch(v: int) -> int:
        return max(0, min(255, round((v * sat + lum * (1.0 - sat)) * bright)))

    return QColor(ch(c.red()), ch(c.green()), ch(c.blue()), c.alpha())


def lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    """Linear per-channel + alpha interpolation, t clamped to [0,1].
    t=0 -> a, t=1 -> b. Used to cross-fade lit <-> dim during the dim animation."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)

    def m(x: int, y: int) -> int:
        return round(x + (y - x) * t)

    return QColor(m(a.red(), b.red()), m(a.green(), b.green()),
                  m(a.blue(), b.blue()), m(a.alpha(), b.alpha()))


def dim_pixmap(pm: QPixmap, sat: float = SAT, bright: float = BRIGHT) -> QPixmap:
    """Return a dimmed copy of `pm` (dim_color per opaque pixel; fully-transparent
    pixels untouched). Caller MUST cache the result - this is a full-image pass and
    is only acceptable on static (inactive) content. `sat`/`bright` default to the
    historic dark-theme filter constants (SAT/BRIGHT); the light palette passes
    (0.35, 1.0) to desaturate without darkening.

    Operates on raw image bytes rather than per-pixel QColor objects (~5-6x faster:
    a 160px portrait drops from ~52ms to ~9ms, within one animation frame, so the
    lit->dim fade no longer stalls the animation timer in transparent/float mode).
    Uses Format_RGBA8888, whose byte order is defined as R,G,B,A on any endianness.
    Output is pixel-identical to the per-channel dim_color() formula."""
    if pm.isNull():
        return pm
    img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
    w = img.width()
    h = img.height()
    stride = img.bytesPerLine()          # row stride may exceed w*4 (padding)
    mv = memoryview(img.bits()).cast("B")  # writable; bits() detaches shared data
    inv = 1.0 - sat
    for y in range(h):
        row = y * stride
        for x in range(w):
            i = row + x * 4
            if mv[i + 3] == 0:
                continue                  # transparent: preserve original bytes
            r = mv[i]
            g = mv[i + 1]
            b = mv[i + 2]
            base = (0.3 * r + 0.59 * g + 0.11 * b) * inv   # luma * (1 - sat)
            vr = round((r * sat + base) * bright)
            vg = round((g * sat + base) * bright)
            vb = round((b * sat + base) * bright)
            mv[i] = 0 if vr < 0 else (255 if vr > 255 else vr)
            mv[i + 1] = 0 if vg < 0 else (255 if vg > 255 else vg)
            mv[i + 2] = 0 if vb < 0 else (255 if vb > 255 else vb)
    del mv                                # release the view before fromImage
    return QPixmap.fromImage(img)
