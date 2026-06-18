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


def darken_rgb(color: QColor, factor: float) -> QColor:
    """Return a copy of `color` with each RGB channel multiplied by `factor`.

    Mirrors the CSS `darken(hex, f)` helper used by the Multitoon pinwheel
    design: a flat per-channel scale (not an HSL lightness scale), so the hue
    stays readable while the colour goes deep and rich. `factor` in (0, 1]
    darkens; alpha is preserved. Channels clamp to [0, 255].
    """
    r = max(0, min(255, round(color.red() * factor)))
    g = max(0, min(255, round(color.green() * factor)))
    b = max(0, min(255, round(color.blue() * factor)))
    return QColor(r, g, b, color.alpha())


def lighten_rgb(color: QColor, factor: float) -> QColor:
    """Return a copy of `color` mixed `factor` of the way toward white.

    Mirrors the CSS `lighten(hex, f)` helper used by the Multitoon pinwheel
    design (portrait tint): `channel + (255 - channel) * factor`. `factor` 0
    returns the colour unchanged, 1 returns white. Alpha is preserved.
    """
    f = max(0.0, min(1.0, factor))
    r = round(color.red() + (255 - color.red()) * f)
    g = round(color.green() + (255 - color.green()) * f)
    b = round(color.blue() + (255 - color.blue()) * f)
    return QColor(r, g, b, color.alpha())


def desaturate(color: QColor, sat_factor: float, bright_factor: float) -> QColor:
    """Return `color` with HSL saturation and lightness scaled.

    Reproduces the Multitoon pinwheel's CSS `filter: saturate(x) brightness(y)`
    idle/dim treatment for a single colour: saturation *= `sat_factor`,
    lightness *= `bright_factor`. Both channels clamp to [0, 255]; hue and
    alpha are preserved. Used to paint dimmed card chrome directly.
    """
    hsl = color.toHsl()
    h = hsl.hslHue()
    s = hsl.hslSaturation()
    l = hsl.lightness()
    a = hsl.alpha()
    new_s = max(0, min(255, round(s * sat_factor)))
    new_l = max(0, min(255, round(l * bright_factor)))
    if h < 0:
        h = 0
    return QColor.fromHsl(h, new_s, new_l, a)
