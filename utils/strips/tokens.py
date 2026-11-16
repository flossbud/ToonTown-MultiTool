"""Colours, colour maths and metrics for the two strip looks.

Every metric is a logical pixel at scale 1.0. The colour helpers are plain
sRGB channel mixes (no HSL), so the values they produce are the ones printed
in the handoff's computed table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient

NEON = "neon"
FLAT = "flat"
STYLES = (NEON, FLAT)

# Movement-set colours, set 1..8.
SET_COLORS = ("#4A8FE7", "#E05252", "#DAA520", "#4CB960",
              "#E08640", "#C4A46C", "#9B6BE0", "#8B6948")
KEEP_ALIVE = "#ff9500"
CLICK_SYNC = "#d4548a"
ENABLE_ON = "#4fc95c"
ENABLE_OFF = "#888888"
BRAND_BLUE = "#0077ff"
ADD_MENU = "#bbbbbb"
POPOVER_BASE = "#161616"
MAX_SETS = 8

FONT_FAMILIES = ("Inter", "Segoe UI", "Noto Sans", "DejaVu Sans")
MONO_FAMILIES = ("JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono")

BODY_ANGLE = 158.0   # degrees, CSS convention (0 = up, clockwise)


def set_color(number: int) -> str:
    """Colour of keyset `number` (1-based)."""
    return SET_COLORS[(int(number) - 1) % len(SET_COLORS)]


# -- colour helpers ---------------------------------------------------------

def _channels(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _round(v: float) -> int:
    # Round half up, the way the reference does (Python's round() is
    # half-to-even and would differ on exact .5 values).
    return int(math.floor(v + 0.5))


def mix(c: str, p: float, base: str) -> str:
    """`c` at p percent, the remainder `base`. Returns '#rrggbb'."""
    a, b = _channels(c), _channels(base)
    out = (_round(v * p / 100.0 + b[i] * (100.0 - p) / 100.0)
           for i, v in enumerate(a))
    return "#" + "".join(f"{max(0, min(255, v)):02x}" for v in out)


def dk(c: str, p: float) -> str:
    """`c` at p percent, the remainder black."""
    return mix(c, p, "#000000")


def lt(c: str, p: float) -> str:
    """`c` at p percent, the remainder white."""
    return mix(c, p, "#ffffff")


def tr(c: str, p: float) -> QColor:
    """`c` at p percent alpha."""
    r, g, b = _channels(c)
    out = QColor(r, g, b)
    out.setAlphaF(max(0.0, min(1.0, p / 100.0)))
    return out


def body(c: str) -> tuple[str, str]:
    """The two stops of the card material: dk(c, 30) -> dk(c, 15), run at
    BODY_ANGLE."""
    return dk(c, 30), dk(c, 15)


def rgba(r: int, g: int, b: int, a: float) -> QColor:
    out = QColor(r, g, b)
    out.setAlphaF(a)
    return out


def css_gradient(rect: QRectF, angle_deg: float, c0, c1) -> QLinearGradient:
    """A two-stop gradient over `rect` laid out the way CSS lays out
    `linear-gradient(<angle>, c0, c1)`: the line runs through the centre and
    is long enough that the corners get exactly the end colours."""
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    half = (abs(rect.width() * dx) + abs(rect.height() * dy)) / 2.0
    c = rect.center()
    g = QLinearGradient(QPointF(c.x() - dx * half, c.y() - dy * half),
                        QPointF(c.x() + dx * half, c.y() + dy * half))
    g.setColorAt(0.0, QColor(c0))
    g.setColorAt(1.0, QColor(c1))
    return g


def body_gradient(rect: QRectF, c: str) -> QLinearGradient:
    c0, c1 = body(c)
    return css_gradient(rect, BODY_ANGLE, c0, c1)


# The Neon look dims a disabled toon's tools and keysets with the CSS filter
# saturate(.35) brightness(.7). Both steps are linear in the colour, so
# filtering each colour before painting gives the same pixels as filtering
# the painted group.
DIM_SATURATE = 0.35
DIM_BRIGHTNESS = 0.7
FLAT_DIM_OPACITY = 0.42


def css_saturate_brightness(c: QColor, s: float = DIM_SATURATE,
                            b: float = DIM_BRIGHTNESS) -> QColor:
    """CSS `saturate(s) brightness(b)` on one colour; alpha is kept."""
    r, g, bl = c.red(), c.green(), c.blue()
    nr = (0.213 + 0.787 * s) * r + (0.715 - 0.715 * s) * g + (0.072 - 0.072 * s) * bl
    ng = (0.213 - 0.213 * s) * r + (0.715 + 0.285 * s) * g + (0.072 - 0.072 * s) * bl
    nb = (0.213 - 0.213 * s) * r + (0.715 - 0.715 * s) * g + (0.072 + 0.928 * s) * bl
    out = QColor(*(max(0, min(255, _round(round(v * b, 6))))
                   for v in (nr, ng, nb)))
    out.setAlpha(c.alpha())
    return out


# -- metrics ----------------------------------------------------------------

@dataclass(frozen=True)
class StripStyle:
    name: str
    gap: float                 # between groups and between blocks in a group
    block: float               # tool / keyset / add / enable square
    radius: float
    portrait: float            # circle diameter, border included
    portrait_border: float
    name_h: float
    name_min_w: float
    name_tuck: float           # how far the plate slides under the portrait
    name_pad_left: float
    name_pad_right: float
    name_border: float
    sep_w: float
    sep_h: float
    sep_margin: float          # each side
    home: float                # circle diameter
    home_margin: float         # after the home block, on top of the gap
    font_name_px: float = 13.0
    font_set_px: float = 14.0
    glyph_bolt: float = 14.0
    glyph_mouse: float = 15.0
    glyph_power: float = 15.0
    glyph_plus: float = 13.0

    @property
    def height(self) -> float:
        """Row height: the portrait is the tallest part."""
        return max(self.portrait, self.block, self.name_h, self.home)

    @property
    def is_neon(self) -> bool:
        return self.name == NEON


NEON_STYLE = StripStyle(
    name=NEON, gap=6, block=28, radius=7, portrait=38, portrait_border=3,
    name_h=26, name_min_w=90, name_tuck=13, name_pad_left=18,
    name_pad_right=10, name_border=2, sep_w=2, sep_h=20, sep_margin=1,
    home=28, home_margin=3)

FLAT_STYLE = StripStyle(
    name=FLAT, gap=5, block=26, radius=4, portrait=36, portrait_border=3,
    name_h=22, name_min_w=86, name_tuck=11, name_pad_left=17,
    name_pad_right=10, name_border=0, sep_w=2, sep_h=22, sep_margin=0,
    home=26, home_margin=3)


def style_for(name: str | None) -> StripStyle:
    return FLAT_STYLE if str(name or "").lower() == FLAT else NEON_STYLE
