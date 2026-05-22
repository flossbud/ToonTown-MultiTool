"""CC badge painting primitives.

Pure functions for the CC badge visual treatment:
- complementary_bg_color: derive a circle bg color from the toon's skin.
- paint_cc_badge: render the full badge (added in a later task).

Kept Qt-aware (QColor / QPainter) but widget-free so the math is unit
testable without instantiating widgets.
"""

from __future__ import annotations

from PySide6.QtGui import QColor


# Saturation below this threshold is treated as achromatic. The threshold
# is the boundary between "this toon has a hue" and "this toon is grayscale".
_ACHROMATIC_SAT_THRESHOLD = 0.15

# Chromatic bg formula: (hue+180, sat*0.25, 0.85). Yields a soft pastel
# complement; lightness ~0.85 keeps it lighter than any natural skin color.
# The design choice is uniform light-pastel for ALL chromatic toons; this
# trades strict WCAG 3:1 contrast for visual uniformity across the grid.
_CHROMATIC_SAT_MULT = 0.25
_CHROMATIC_LIGHTNESS = 0.85

# Achromatic bg lightness flip targets. ~65pp delta from input lightness.
_ACHROMATIC_DARK_THRESHOLD = 0.50  # input lightness below this -> light bg
_ACHROMATIC_LIGHT_BG = 0.90
_ACHROMATIC_DARK_BG = 0.25


def complementary_bg_color(skin: QColor) -> QColor:
    """Return the badge background color for a given skin color.

    Chromatic skins (sat > threshold): soft pastel complementary hue at
    L=0.85 -- uniform light-pastel for all chromatic toons.
    Achromatic skins: grayscale lightness flip (dark skin -> light bg,
    light skin -> dark bg).
    """
    h, s, l, _ = skin.getHslF()
    # QColor.getHslF returns hue = -1 for achromatic colors. Normalize.
    if h < 0:
        h = 0.0

    if s <= _ACHROMATIC_SAT_THRESHOLD:
        bg_light = (
            _ACHROMATIC_LIGHT_BG
            if l < _ACHROMATIC_DARK_THRESHOLD
            else _ACHROMATIC_DARK_BG
        )
        return QColor.fromHslF(0.0, 0.0, bg_light)

    new_h = (h + 0.5) % 1.0  # +180 degrees in [0,1] space
    new_s = s * _CHROMATIC_SAT_MULT
    return QColor.fromHslF(new_h, new_s, _CHROMATIC_LIGHTNESS)
