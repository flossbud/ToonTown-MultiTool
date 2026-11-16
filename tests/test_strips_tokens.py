"""Colour maths for the float strips, against the handoff's computed table."""
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from utils.strips import tokens
from utils.strips.tokens import body, dk, lt, tr

# c, lt62 (lit border), dk30 -> dk15 (unlit gradient), lt55 (unlit glyph)
TABLE = [
    ("#ff9500", "#ffbd61", "#4d2d00", "#261600", "#ffc573"),
    ("#d4548a", "#e495b6", "#401929", "#200d15", "#e7a1bf"),
    ("#4fc95c", "#92de9a", "#183c1c", "#0c1e0e", "#9ee1a5"),
    ("#888888", "#b5b5b5", "#292929", "#141414", "#bebebe"),
    ("#4A8FE7", "#8fbaf0", "#162b45", "#0b1523", "#9bc1f2"),
    ("#E05252", "#ec9494", "#431919", "#220c0c", "#eea0a0"),
    ("#DAA520", "#e8c775", "#41320a", "#211905", "#ebce84"),
    ("#4CB960", "#90d49c", "#17381d", "#0b1c0e", "#9dd9a8"),
    ("#E08640", "#ecb489", "#432813", "#22140a", "#eebc96"),
    ("#C4A46C", "#dac7a4", "#3b3120", "#1d1910", "#dfcdae"),
    ("#9B6BE0", "#c1a3ec", "#2f2043", "#171022", "#c8aeee"),
    ("#8B6948", "#b7a28e", "#2a2016", "#15100b", "#bfad9a"),
]


@pytest.mark.parametrize("c,lt62,dk30,dk15,lt55", TABLE)
def test_computed_table(c, lt62, dk30, dk15, lt55):
    assert lt(c, 62) == lt62
    assert dk(c, 30) == dk30
    assert dk(c, 15) == dk15
    assert lt(c, 55) == lt55
    assert body(c) == (dk30, dk15)


def test_table_covers_every_block_colour():
    table = {row[0].lower() for row in TABLE}
    used = {c.lower() for c in tokens.SET_COLORS} | {
        tokens.KEEP_ALIVE, tokens.CLICK_SYNC, tokens.ENABLE_ON, tokens.ENABLE_OFF}
    assert used == table


def test_tr_keeps_the_colour_and_sets_alpha():
    c = tr("#4A8FE7", 45)
    assert (c.red(), c.green(), c.blue()) == (0x4A, 0x8F, 0xE7)
    assert c.alphaF() == pytest.approx(0.45, abs=0.003)


def test_set_colours_are_one_based():
    assert tokens.set_color(1) == "#4A8FE7"
    assert tokens.set_color(8) == "#8B6948"


def test_dim_filter_is_css_saturate_then_brightness():
    # White and black have no chroma: only brightness(.7) acts on them.
    assert tokens.css_saturate_brightness(QColor("#ffffff")).name() == "#b3b3b3"
    assert tokens.css_saturate_brightness(QColor("#000000")).name() == "#000000"
    dim = tokens.css_saturate_brightness(tr("#4A8FE7", 60))
    assert dim.alphaF() == pytest.approx(0.6, abs=0.003)
    # Less chroma, darker, hue order kept.
    assert dim.blue() > dim.green() > dim.red()
    assert dim.blue() - dim.red() < 0xE7 - 0x4A
    assert dim.blue() < 0xE7


def test_body_gradient_runs_down_and_slightly_right():
    g = tokens.body_gradient(QRectF(0, 0, 28, 28), "#4A8FE7")
    assert g.finalStop().y() > g.start().y()
    assert g.finalStop().x() > g.start().x()
    stops = g.stops()
    assert stops[0][1].name() == "#162b45" and stops[-1][1].name() == "#0b1523"


def test_metrics_match_the_anatomy_table():
    n, f = tokens.NEON_STYLE, tokens.FLAT_STYLE
    assert (n.gap, n.block, n.radius, n.portrait, n.name_h, n.name_min_w,
            n.name_tuck, n.sep_h, n.home) == (6, 28, 7, 38, 26, 90, 13, 20, 28)
    assert (f.gap, f.block, f.radius, f.portrait, f.name_h, f.name_min_w,
            f.name_tuck, f.sep_h, f.home) == (5, 26, 4, 36, 22, 86, 11, 22, 26)
    assert tokens.style_for("flat") is f
    assert tokens.style_for("neon") is n
    assert tokens.style_for(None) is n          # Neon is the default look
