"""Pure color-space helpers. No widget deps; only QColor."""

from __future__ import annotations

from PySide6.QtGui import QColor


def darken_hsl(color: QColor, factor: float) -> QColor:
    """Return a copy of `color` with HSL lightness multiplied by `factor`.

    Hue, saturation, and alpha are preserved. `factor` in (0, 1] darkens;
    values > 1 lighten. The lightness channel is clamped to [0, 255]
    after scaling so pure black and pure white don't underflow / overflow.

    Achromatic inputs (saturation 0) report hue == -1 in Qt; we coerce to
    0 so `QColor.fromHsl` produces a valid neutral gray.
    """
    hsl = color.toHsl()
    h = hsl.hslHue()
    s = hsl.hslSaturation()
    l = hsl.lightness()
    a = hsl.alpha()
    new_l = max(0, min(255, round(l * factor)))
    if h < 0:
        h = 0
    return QColor.fromHsl(h, s, new_l, a)
