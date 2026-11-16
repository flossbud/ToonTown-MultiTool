"""The painted strip under the app's real stylesheet, mounted in a parent.

The parent paints magenta, a colour no strip block uses: wherever the strip
is supposed to be see-through, the grab must still be magenta.
"""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from utils import theme_manager
from utils.strips import layout as L
from utils.strips import paint, tokens
from utils.strips.model import StripModel
from utils.strips.strip_widget import MARGIN, StripWidget

MAGENTA = QColor(255, 0, 255)


class Host(QWidget):
    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), MAGENTA)


@contextmanager
def _temporary_theme(qapp, theme):
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    try:
        theme_manager.apply_theme(qapp, theme)
        yield
    finally:
        qapp.setStyleSheet(before_sheet)
        qapp.setPalette(before_palette)
        theme_manager._APPLIED_THEME = before_marker


@pytest.fixture(params=["light", "dark"])
def themed_app(qapp, request):
    with _temporary_theme(qapp, request.param):
        yield qapp


@pytest.fixture
def mount(themed_app):
    hosts = []

    def _mount(model, style="neon", scale=1.0, client_width=None):
        host = Host()
        host.resize(700, 120)
        strip = StripWidget(host)
        strip.set_style(style)
        strip.set_scale(scale)
        strip.set_client_width(client_width)
        strip.set_model(model)
        strip.move(20, 20)
        host.show()
        QApplication.processEvents()
        hosts.append(host)
        return host, strip

    yield _mount
    for host in hosts:
        host.close()
        host.deleteLater()


def grab(host):
    QApplication.processEvents()
    return host.grab().toImage()


def at(image, strip, rect, dx, dy):
    """Pixel at an offset from a strip-local rect's top-left corner."""
    p = strip.pos() + QPoint(int(rect.x() + dx), int(rect.y() + dy))
    return image.pixelColor(p)


def close(a, b, tolerance=3):
    b = QColor(b)
    return (abs(a.red() - b.red()) <= tolerance
            and abs(a.green() - b.green()) <= tolerance
            and abs(a.blue() - b.blue()) <= tolerance)


FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")


def test_strip_has_no_background_between_blocks(mount):
    host, strip = mount(FLOSSBUD, "flat")
    image = grab(host)
    two, three = strip.block_rect(L.KEYSET, 2), strip.block_rect(L.KEYSET, 3)
    gap_x = (two.right() + three.left()) / 2.0
    p = strip.pos() + QPoint(int(gap_x), int(two.center().y()))
    assert image.pixelColor(p) == MAGENTA
    # Corners of the widget, far outside any block.
    assert image.pixelColor(strip.pos() + QPoint(1, 1)) == MAGENTA
    assert image.pixelColor(strip.geometry().bottomRight() - QPoint(1, 1)) == MAGENTA


def test_neon_lit_and_unlit_signs(mount):
    host, strip = mount(FLOSSBUD, "neon")
    image = grab(host)
    lit = strip.block_rect(L.KEYSET, 1)
    assert close(at(image, strip, lit, 6, 6), "#4A8FE7")           # fill
    assert close(at(image, strip, lit, 14, 1), tokens.lt("#4A8FE7", 62))  # border
    unlit = at(image, strip, strip.block_rect(L.KEYSET, 2), 6, 6)
    # body(#E05252): somewhere between dk15 and dk30, red-dominant.
    assert 0x22 <= unlit.red() <= 0x43 and unlit.red() > 2 * unlit.green()
    assert close(at(image, strip, strip.block_rect(L.KEEP_ALIVE), 5, 5), "#ff9500")
    assert close(at(image, strip, strip.block_rect(L.ENABLE), 5, 5), "#4fc95c")


def test_neon_glow_spills_outside_a_lit_block_only(mount):
    host, strip = mount(FLOSSBUD.with_(click_sync=False), "neon")
    image = grab(host)
    lit = strip.block_rect(L.KEEP_ALIVE)
    halo = at(image, strip, lit, 14, -2)
    assert halo != MAGENTA and halo.green() > 20       # orange over magenta
    unlit = strip.block_rect(L.CLICK_SYNC)
    assert at(image, strip, unlit, 14, 31) == MAGENTA


def test_flat_fills_and_active_ring(mount):
    host, strip = mount(FLOSSBUD, "flat")
    image = grab(host)
    active = strip.block_rect(L.KEYSET, 1)
    assert close(at(image, strip, active, 13, 1), "#ffffff")       # inset ring
    assert close(at(image, strip, active, 5, 5), "#4A8FE7")
    inactive = strip.block_rect(L.KEYSET, 2)
    assert close(at(image, strip, inactive, 5, 5), tokens.dk("#E05252", 46))
    assert close(at(image, strip, inactive, 13, 1), tokens.dk("#E05252", 46))
    # No halo anywhere in Flat.
    assert at(image, strip, active, 13, -2) == MAGENTA


def test_tools_off_are_unlit(mount):
    host, strip = mount(FLOSSBUD.with_(keep_alive=False, click_sync=False), "flat")
    image = grab(host)
    assert close(at(image, strip, strip.block_rect(L.KEEP_ALIVE), 4, 4),
                 tokens.dk("#ff9500", 30))
    assert close(at(image, strip, strip.block_rect(L.CLICK_SYNC), 4, 4),
                 tokens.dk("#d4548a", 30))


def test_disabled_toon_dims_tools_and_keysets_but_not_enable(mount):
    host, strip = mount(FLOSSBUD.with_(enabled=False), "neon")
    image = grab(host)
    lit = at(image, strip, strip.block_rect(L.KEYSET, 1), 6, 6)
    assert close(lit, tokens.css_saturate_brightness(QColor("#4A8FE7")))
    # Enable shows its own off state at full strength: unlit grey sign.
    enable = at(image, strip, strip.block_rect(L.ENABLE), 6, 6)
    assert 0x14 <= enable.red() <= 0x29 and enable.red() == enable.green()
    # Identity goes neutral.
    plate = strip.block_rect(L.NAME)
    assert close(at(image, strip, plate, plate.width() - 8, 6), "#222222")


def test_flat_disabled_group_fades_as_one_layer(mount):
    host, strip = mount(FLOSSBUD.with_(enabled=False), "flat")
    image = grab(host)
    active = strip.block_rect(L.KEYSET, 1)

    def over_magenta(c):
        c = QColor(c)
        a = tokens.FLAT_DIM_OPACITY
        return QColor(round(c.red() * a + 255 * (1 - a)),
                      round(c.green() * a),
                      round(c.blue() * a + 255 * (1 - a)))

    assert close(at(image, strip, active, 5, 5), over_magenta("#4A8FE7"), 4)
    # The ring fades with the block: white at 42%, not white over the fill.
    assert close(at(image, strip, active, 13, 1), over_magenta("#ffffff"), 4)
    assert close(at(image, strip, strip.block_rect(L.NAME), 60, 4), "#4a4a4a")


def test_stopped_service_dims_like_a_disabled_toon_and_keeps_enable_lit(mount):
    host, strip = mount(FLOSSBUD.with_(running=False), "neon")
    image = grab(host)
    assert close(at(image, strip, strip.block_rect(L.KEYSET, 1), 6, 6),
                 tokens.css_saturate_brightness(QColor("#4A8FE7")))
    assert close(at(image, strip, strip.block_rect(L.ENABLE), 5, 5), "#4fc95c")


def test_identity_colours(mount):
    host, strip = mount(FLOSSBUD, "flat")
    image = grab(host)
    plate = strip.block_rect(L.NAME)
    assert close(at(image, strip, plate, plate.width() - 6, 4), "#4a8fe7")
    portrait = strip.block_rect(L.PORTRAIT)
    assert close(at(image, strip, portrait, 18, 1), "#4a8fe7")               # border
    assert close(at(image, strip, portrait, 18, 5), tokens.lt("#4a8fe7", 55))  # fill
    # The silhouette is drawn: some pixel in the middle is its dk(42) tint.
    tint = QColor(tokens.dk("#4a8fe7", 42))
    assert any(close(at(image, strip, portrait, x, y), tint, 6)
               for x in range(10, 27) for y in range(10, 27))


def test_text_is_pixel_sized_by_the_strip_not_the_stylesheet(themed_app):
    assert paint.strip_font(14, 800).pixelSize() == 14
    assert paint.name_font(tokens.NEON_STYLE).pixelSize() == 13
    host = Host()
    strip = StripWidget(host)
    strip.set_model(FLOSSBUD.with_(name="A much longer toon name"))
    text_w = paint.measure_name(tokens.NEON_STYLE, "A much longer toon name")
    assert strip.block_rect(L.NAME).width() == pytest.approx(2 + 18 + text_w + 10 + 2)
    host.deleteLater()


def test_clicks_report_the_block(mount):
    host, strip = mount(FLOSSBUD)
    clicks, menus = [], []
    strip.clicked.connect(lambda kind, n: clicks.append((kind, n)))
    strip.context_requested.connect(lambda kind, n: menus.append((kind, n)))

    def centre(kind, n=0):
        return strip.block_rect(kind, n).center().toPoint()

    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, centre(L.KEYSET, 2))
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, centre(L.ENABLE))
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, centre(L.ADD))
    QTest.mouseClick(strip, Qt.RightButton, Qt.NoModifier, centre(L.KEYSET, 3))
    QTest.mouseClick(strip, Qt.RightButton, Qt.NoModifier, centre(L.PORTRAIT))
    assert clicks == [(L.KEYSET, 2), (L.ENABLE, 0), (L.ADD, 0)]
    assert menus == [(L.KEYSET, 3), (L.PORTRAIT, 0)]

    # A press that slides off its block is not a click.
    clicks.clear()
    QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, centre(L.KEYSET, 1))
    QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, centre(L.KEYSET, 2))
    assert clicks == []
    # Nor is a click in the gap between blocks or on a separator.
    sep = strip.block_rect(L.SEPARATOR).center().toPoint()
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, sep)
    assert clicks == []


def test_input_rects_cover_the_blocks_and_nothing_else(mount):
    host, strip = mount(FLOSSBUD.with_(home=True))
    rects = strip.input_rects()
    # home, portrait, name, 2 tools, 3 keysets, add, enable
    assert len(rects) == 10
    sep = strip.block_rect(L.SEPARATOR).center().toPoint()
    assert not any(r.contains(sep) for r in rects)
    assert not any(r.contains(QPoint(2, 2)) for r in rects)
    for r in rects:
        assert strip.rect().contains(r)


def test_scale_keeps_the_strip_true_size(mount):
    """With the app shrunk by QT_SCALE_FACTOR 0.8 the surface asks for 1.25:
    every block is 1.25 times as large in widget px."""
    host, strip = mount(FLOSSBUD, scale=1.25)
    assert strip.block_rect(L.ENABLE).width() == pytest.approx(35.0)
    assert strip.width() == round((strip.strip_layout().width + 2 * MARGIN) * 1.25)
    image = grab(host)
    assert close(at(image, strip, strip.block_rect(L.KEYSET, 1), 8, 8), "#4A8FE7")


def test_narrow_client_collapses_the_name(mount):
    host, strip = mount(FLOSSBUD, client_width=320)
    assert strip.strip_layout().collapse == L.NO_NAME
    assert strip.block_rect(L.NAME) is None
    assert strip.row_size().width() == 373 - 77


def test_every_state_paints_in_both_looks(mount):
    states = [
        FLOSSBUD.with_(keysets=(1,)),
        FLOSSBUD.with_(keysets=tuple(range(1, 9)), active=5, show_add=False),
        FLOSSBUD.with_(enabled=False),
        FLOSSBUD.with_(keep_alive=None, click_sync=None),
        FLOSSBUD.with_(keysets=(1, 2), hidden_sets=True, home=True, home_open=True),
        FLOSSBUD.with_(home=True, running=False, species=None),
    ]
    for style in tokens.STYLES:
        for model in states:
            host, strip = mount(model, style)
            image = grab(host)
            enable = strip.block_rect(L.ENABLE)
            assert at(image, strip, enable, 5, 5) != MAGENTA


def test_number_block_paints_without_a_strip_widget(qapp):
    """The window's Keysets sheet reuses the block: a painter, a rect, a
    number, lit or not, and the look."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage

    def render(look, lit):
        image = QImage(60, 60, QImage.Format_ARGB32_Premultiplied)
        image.fill(MAGENTA)
        p = QPainter(image)
        paint.paint_number_block(p, QRectF(16, 16, 28, 28), 2, lit, look)
        p.end()
        return image

    lit = render("neon", True)
    assert close(lit.pixelColor(21, 21), "#E05252")
    assert lit.pixelColor(30, 13) != MAGENTA                 # halo
    unlit = render("neon", False)
    assert unlit.pixelColor(30, 13) == MAGENTA               # no halo
    assert unlit.pixelColor(21, 21).red() < 0x50
    flat = render("flat", True)
    assert close(flat.pixelColor(30, 17), "#ffffff")         # inset ring
    assert flat.pixelColor(30, 13) == MAGENTA
    assert close(render("flat", False).pixelColor(21, 21), tokens.dk("#E05252", 46))


def test_click_sync_error_is_unlit_with_an_amber_dot(mount):
    model = FLOSSBUD.with_(click_sync=True, click_sync_state="error")
    host, strip = mount(model, "flat")
    image = grab(host)
    block = strip.block_rect(L.CLICK_SYNC)
    assert close(at(image, strip, block, 4, 20), tokens.dk("#d4548a", 30))   # unlit
    assert close(at(image, strip, block, block.width() - 5, 5), "#ffb020")   # dot
    # Armed is still lit and carries no dot.
    host, strip = mount(FLOSSBUD.with_(click_sync_state="armed"), "flat")
    image = grab(host)
    block = strip.block_rect(L.CLICK_SYNC)
    assert close(at(image, strip, block, 4, 20), "#d4548a")
    assert close(at(image, strip, block, block.width() - 5, 5), "#d4548a")


def test_a_real_portrait_fills_the_circle_inside_its_border(mount):
    from PySide6.QtGui import QPixmap
    pm = QPixmap(96, 96)
    pm.fill(QColor("#00ff00"))
    host, strip = mount(FLOSSBUD.with_(portrait=pm), "flat")
    image = grab(host)
    portrait = strip.block_rect(L.PORTRAIT)
    assert close(at(image, strip, portrait, 18, 18), "#00ff00")     # the render
    assert close(at(image, strip, portrait, 18, 1), "#4a8fe7")      # border kept
    assert at(image, strip, portrait, 1, 1) == MAGENTA              # clipped round


# -- transitions ---------------------------------------------------------------------

def test_state_change_cross_fades_and_lands_on_the_new_state(mount, qapp):
    host, strip = mount(FLOSSBUD, "flat")
    strip.set_reduced_motion_fn(lambda: False)
    grab(host)
    block = strip.block_rect(L.KEEP_ALIVE)
    strip.set_model(FLOSSBUD.with_(keep_alive=False))
    assert strip.is_fading()
    # Mid-fade the block is between lit and unlit, and still fully opaque.
    strip._fade.pause()
    strip._fade.setCurrentTime(70)
    mid = at(grab(host), strip, block, 4, 4)
    lit, unlit = QColor("#ff9500"), QColor(tokens.dk("#ff9500", 30))
    assert unlit.red() + 15 < mid.red() < lit.red() - 15
    assert mid.blue() < 30                       # no magenta showing through
    strip._fade.setCurrentTime(140)
    strip._end_fade()
    assert not strip.is_fading()
    assert close(at(grab(host), strip, block, 4, 4), unlit)


def test_dim_fades_a_little_longer(mount):
    host, strip = mount(FLOSSBUD, "neon")
    strip.set_reduced_motion_fn(lambda: False)
    strip.set_model(FLOSSBUD.with_(enabled=False))
    assert strip.is_fading() and strip._fade.duration() == 200
    strip._end_fade()
    strip.set_model(FLOSSBUD.with_(enabled=False, keep_alive=False))
    assert strip._fade.duration() == 140


def test_reduced_motion_snaps(mount):
    host, strip = mount(FLOSSBUD, "flat")
    strip.set_reduced_motion_fn(lambda: True)
    strip.set_model(FLOSSBUD.with_(keep_alive=False))
    assert not strip.is_fading()
    assert close(at(grab(host), strip, strip.block_rect(L.KEEP_ALIVE), 4, 4),
                 tokens.dk("#ff9500", 30))


def test_a_layout_change_is_never_faded(mount):
    host, strip = mount(FLOSSBUD, "flat")
    strip.set_reduced_motion_fn(lambda: False)
    strip.set_model(FLOSSBUD.with_(keysets=(1, 2)))      # a block went away
    assert not strip.is_fading()


def test_saved_portrait_framing_is_applied(mount):
    """A render that is green on its left half and red on its right: moved
    half a circle to the left, the middle of the portrait turns red."""
    from PySide6.QtGui import QPixmap
    pm = QPixmap(96, 96)
    pm.fill(QColor("#ff0000"))
    painter = QPainter(pm)
    painter.fillRect(0, 0, 48, 96, QColor("#00ff00"))
    painter.end()
    host, strip = mount(FLOSSBUD.with_(portrait=pm), "flat")
    portrait = strip.block_rect(L.PORTRAIT)
    assert close(at(grab(host), strip, portrait, 12, 18), "#00ff00", 12)
    host, strip = mount(FLOSSBUD.with_(portrait=pm, portrait_frame=(1.0, -0.4, 0.0, 0.0)),
                        "flat")
    assert close(at(grab(host), strip, portrait, 12, 18), "#ff0000", 12)
    # Zoomed in, the same pixels cover more of the circle; still clipped round.
    host, strip = mount(FLOSSBUD.with_(portrait=pm, portrait_frame=(2.0, 0.0, 0.0, 0.0)),
                        "flat")
    image = grab(host)
    assert close(at(image, strip, portrait, 8, 18), "#00ff00", 12)
    assert at(image, strip, portrait, 1, 1) == MAGENTA


def test_a_disabled_toons_portrait_goes_grey(mount):
    from PySide6.QtGui import QPixmap
    pm = QPixmap(96, 96)
    pm.fill(QColor("#00ff00"))
    host, strip = mount(FLOSSBUD.with_(portrait=pm, enabled=False), "flat")
    grey = at(grab(host), strip, strip.block_rect(L.PORTRAIT), 18, 18)
    assert abs(grey.red() - grey.green()) <= 2 and abs(grey.green() - grey.blue()) <= 2
    assert 40 < grey.green() < 140


def test_stopped_service_dims_the_home_icon(mount):
    lit_host, lit = mount(FLOSSBUD.with_(home=True), "flat")
    dim_host, dim = mount(FLOSSBUD.with_(home=True, running=False), "flat")
    home = lit.block_rect(L.HOME)
    a = at(grab(lit_host), lit, home, 14, 6)
    b = at(grab(dim_host), dim, home, 14, 6)
    assert b.red() + b.green() + b.blue() < a.red() + a.green() + a.blue()
    assert at(grab(dim_host), dim, home, 1, 1) == MAGENTA      # still a circle
