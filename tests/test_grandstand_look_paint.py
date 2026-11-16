"""paint_look_disc: the one disc painter of the appearance editor.

It must draw what production's badge draws from the same stored entry, so
the framing assertions below restate production's transform (rotate about
the centre, offset in zoomed circle fractions, zoom baked into the scale).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from utils.icon_factory import (
    make_check_icon, make_chevron_down_icon, make_swap_icon,
)
from utils.widgets.grandstand.look_paint import (
    ART_INSET, PATTERN_TILE, paint_look_disc, pattern_tile_for,
)

D = 240
CLEAR = QColor(0, 0, 0, 0)
RED, GREEN, BLUE, WHITE = (QColor(c) for c in ("#ff0000", "#00ff00", "#0000ff", "#ffffff"))


def _near(a, b, slack=6):
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue())) <= slack


def _solid(colour, size=64):
    pm = QPixmap(size, size)
    pm.fill(colour)
    return pm


def _islet(colour, size=64, inner=32):
    """An opaque square centred in a transparent one: art with an edge."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    edge = (size - inner) // 2
    p.fillRect(edge, edge, inner, inner, colour)
    p.end()
    return pm


def _paint(entry, **kwargs):
    img = QImage(D, D, QImage.Format_ARGB32_Premultiplied)
    img.fill(CLEAR)
    p = QPainter(img)
    kwargs.setdefault("fill_fallback", QColor("#4a4a4a"))
    kwargs.setdefault("accent_fallback", BLUE)
    kwargs.setdefault("ring_width", 0)
    paint_look_disc(p, QRectF(0, 0, D, D), entry, **kwargs)
    p.end()
    return img


def test_nothing_is_painted_outside_the_circle(qapp):
    img = _paint({"portrait": {"color": "#00ff00"}}, art=_solid(RED), ring_width=4)
    for x, y in ((2, 2), (D - 3, 2), (2, D - 3), (D - 3, D - 3)):
        assert img.pixelColor(x, y).alpha() == 0
    assert img.pixelColor(D // 2, D // 2).alpha() == 255


def test_the_backdrop_is_the_resolved_brush_or_the_fallback(qapp):
    assert _near(_paint({"portrait": {"color": "#00ff00"}}).pixelColor(120, 120), GREEN)
    assert _near(_paint({}).pixelColor(120, 120), QColor("#4a4a4a"))
    # Gradient beats colour, and runs top-left to bottom-right (CSS 135deg).
    img = _paint({"portrait": {"color": "#00ff00",
                               "gradient": {"start": "#ff0000", "end": "#0000ff"}}})
    top_left, bottom_right = img.pixelColor(60, 60), img.pixelColor(180, 180)
    assert top_left.red() > top_left.blue()
    assert bottom_right.blue() > bottom_right.red()
    assert top_left.green() < 20


def test_the_ring_is_the_accent_or_its_fallback(qapp):
    assert _near(_paint({"accent": "#ff0000"}, ring_width=4).pixelColor(120, 1), RED, 20)
    assert _near(_paint({}, ring_width=4).pixelColor(120, 1), BLUE, 20)
    assert _near(_paint({}, ring_width=0).pixelColor(120, 1), QColor("#4a4a4a"), 20)


def test_an_unknown_pattern_paints_nothing_and_does_not_raise(qapp):
    img = _paint({"portrait": {"color": "#00ff00",
                               "pattern": {"name": "tartan", "color": "#ffffff"}}})
    assert _near(img.pixelColor(120, 120), GREEN)


def test_the_pattern_tile_keeps_productions_ratio(qapp):
    """24 px on the 172 px Multitoon badge; the same coarseness on any disc."""
    assert pattern_tile_for(172) == PATTERN_TILE == 24
    assert pattern_tile_for(240) == 33
    assert pattern_tile_for(56) == 8
    assert pattern_tile_for(10) == 6                      # never a smear


def test_art_fills_the_disc_unframed(qapp):
    img = _paint({"portrait": {"color": "#00ff00",
                               "transform": {"zoom": 0.5, "offset_x": 0.5}}},
                 art=_solid(RED))
    # Not `framed`: a Look swatch ignores the stored framing.
    assert _near(img.pixelColor(120, 120), RED)
    assert _near(img.pixelColor(30, 120), RED)


def test_framed_art_takes_productions_zoom(qapp):
    entry = {"portrait": {"color": "#00ff00", "transform": {"zoom": 0.5}}}
    img = _paint(entry, art=_solid(RED), framed=True)
    assert _near(img.pixelColor(120, 120), RED)           # 120 px square, centred
    assert _near(img.pixelColor(70, 120), RED)
    assert _near(img.pixelColor(50, 120), GREEN)          # outside it: the backdrop
    assert _near(img.pixelColor(120, 190), GREEN)


def test_framed_offsets_are_circle_fractions_scaled_by_the_zoom(qapp):
    """Production: translate(int(off * d) * zoom). At zoom 0.5 an offset of
    0.25 moves the art 30 px, not 60."""
    entry = {"portrait": {"color": "#00ff00", "transform": {
        "zoom": 0.5, "offset_x": 0.25, "offset_y": 0.0}}}
    img = _paint(entry, art=_solid(RED), framed=True)
    # The 120 px square now spans x = 90 .. 210.
    assert _near(img.pixelColor(95, 120), RED)
    assert _near(img.pixelColor(205, 120), RED)
    assert _near(img.pixelColor(85, 120), GREEN)
    assert _near(img.pixelColor(215, 120), GREEN)


def test_framed_rotation_turns_the_offset_with_the_art(qapp):
    """Rotate first, then offset: a +x offset under a 90 degree turn moves
    the art down the screen."""
    entry = {"portrait": {"color": "#00ff00", "transform": {
        "zoom": 0.25, "offset_x": 1.0, "offset_y": 0.0, "rotate": 90}}}
    img = _paint(entry, art=_solid(RED), framed=True)
    assert _near(img.pixelColor(120, 180), RED)           # 60 px below centre
    assert _near(img.pixelColor(180, 120), GREEN)


def test_species_art_is_inset(qapp):
    assert ART_INSET == 0.8
    img = _paint({"portrait": {"color": "#00ff00"}}, art=_solid(RED),
                 art_scale=ART_INSET)
    assert _near(img.pixelColor(120, 120), RED)
    assert _near(img.pixelColor(30, 120), RED)            # 24 .. 216
    assert _near(img.pixelColor(18, 120), GREEN)


def test_a_stored_silhouette_outline_is_drawn_on_the_framed_canvas(qapp):
    """The editor has no control for it, but a look that carries one must
    not preview without it."""
    plain = {"portrait": {"color": "#00ff00"}}
    outlined = {"portrait": {"color": "#00ff00", "silhouette": {
        "outline": {"color": "#ffffff", "width": "thick"}}}}
    art = _islet(RED, size=D, inner=120)                  # drawn 1:1, no blur
    # The islet's edge is at x = 60. Two pixels outside it is backdrop
    # without the outline and white with it ("thick" is 3 px).
    assert _near(_paint(plain, art=art, framed=True).pixelColor(58, 120), GREEN)
    assert _near(_paint(outlined, art=art, framed=True).pixelColor(58, 120), WHITE, 40)
    assert _near(_paint(outlined, art=art, framed=True).pixelColor(120, 120), RED)


def test_a_non_numeric_transform_reads_as_neutral(qapp):
    entry = {"portrait": {"color": "#00ff00", "transform": {"zoom": "big"}}}
    img = _paint(entry, art=_solid(RED), framed=True)
    assert _near(img.pixelColor(30, 120), RED)            # zoom 1: fills the disc


def test_an_empty_rect_and_a_non_dict_entry_are_harmless(qapp):
    img = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(CLEAR)
    p = QPainter(img)
    paint_look_disc(p, QRectF(0, 0, 0, 0), {}, fill_fallback=RED,
                    accent_fallback=BLUE, ring_width=2)
    paint_look_disc(p, QRectF(0, 0, 8, 8), None, fill_fallback=RED,
                    accent_fallback=BLUE, ring_width=0)
    p.end()
    assert _near(img.pixelColor(4, 4), RED)


# ── the painted icons (no symbol glyph stands in for one) ───────────────────

@pytest.mark.parametrize("factory", [make_check_icon, make_chevron_down_icon,
                                     make_swap_icon])
def test_each_new_icon_paints_strokes_in_the_colour_it_is_given(qapp, factory):
    img = factory(24, RED).pixmap(24, 24).toImage()
    inked = [img.pixelColor(x, y) for x in range(24) for y in range(24)
             if img.pixelColor(x, y).alpha() > 200]
    assert len(inked) > 12
    assert all(_near(c, RED, 12) for c in inked)
    assert img.pixelColor(0, 0).alpha() == 0              # transparent ground


def test_the_three_icons_are_different_drawings(qapp):
    def mask(factory):
        img = factory(24, RED).pixmap(24, 24).toImage()
        return tuple(img.pixelColor(x, y).alpha() > 128
                     for x in range(24) for y in range(24))
    assert len({mask(f) for f in (make_check_icon, make_chevron_down_icon,
                                  make_swap_icon)}) == 3
