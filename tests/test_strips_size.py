"""Strip size (small / medium / large), the device pixel grid a scaled strip
is drawn on, and the drop shadow under every block."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_strips_controller import (            # noqa: F401  (fixtures)
    Backend, Keymaps, Launcher, Settings, Strategy, WIDS, _session_with_ids,
    click, home_rig, model, rig, right_click, settle,
)
from utils import settings_keys as sk
from utils import ui_scale
from utils.strips import layout as L
from utils.strips import paint, tokens
from utils.strips.follow import StripFollower
from utils.strips.model import StripModel
from utils.strips.strip_surface import ANCHOR_INSET, StripSurface, strip_scale
from utils.strips.strip_widget import MARGIN, StripWidget

MAGENTA = QColor(255, 0, 255)
FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")
SIZES = (("small", 1.0), ("medium", 1.25), ("large", 1.5))


# -- one function for the scale ------------------------------------------------

def test_strip_scale_is_true_size_times_the_size_factor():
    assert strip_scale({}) == 1.0                              # no size: no factor
    assert strip_scale({}, "small") == 1.0
    assert strip_scale({}, "medium") == 1.25
    assert strip_scale({}, "large") == 1.5
    assert strip_scale({}, "nonsense") == 1.25                 # the default size
    shrunk = {ui_scale.ENV_ACTIVE: "0.8"}                      # the app at 80 %
    assert strip_scale(shrunk) == pytest.approx(1.25)
    assert strip_scale(shrunk, "medium") == pytest.approx(1.5625)
    assert strip_scale({ui_scale.ENV_ACTIVE: "junk"}, "large") == 1.5


@pytest.mark.parametrize("size,factor", SIZES)
def test_follower_builds_every_strip_at_its_size(qapp, size, factor):
    follower = StripFollower(Strategy(), Backend(), geometry_fn=lambda w: None,
                             scale=1.0, size=size)
    assert follower.size() == size and follower.scale() == factor
    surface = follower.add("7")
    assert surface.strip.scale() == factor
    assert surface.strip.block_rect(L.ENABLE).width() == pytest.approx(28 * factor)
    follower.shutdown()


def test_the_true_size_scale_and_the_size_factor_multiply(qapp):
    follower = StripFollower(Strategy(), Backend(), geometry_fn=lambda w: None,
                             scale=1.25, size="large")
    assert follower.scale() == pytest.approx(1.875)
    follower.shutdown()


def test_stamp_names_the_size(qapp, capsys, monkeypatch):
    from utils.strips import follow
    monkeypatch.setattr(follow, "_stamped", False)
    follower = StripFollower(Strategy(), Backend(), geometry_fn=lambda w: None,
                             style="flat", size="large")
    follower.start()
    follower.shutdown()
    assert "[Strips] attach=test style=flat size=large" in capsys.readouterr().out


def test_a_new_size_reaches_placed_strips_where_they_stand(qapp):
    rects = {"7": (100, 50, 800, 600)}
    follower = StripFollower(Strategy(), Backend(), geometry_fn=rects.get, scale=1.0)
    surface = follower.add("7")
    surface.set_model(FLOSSBUD)
    follower.tracker.sample_now()
    follower.tracker.sample_now()
    settle()
    assert surface.is_presented()

    def row():
        offset = surface.strip.row_offset()
        return QRect(surface.geometry().topLeft() + QPoint(round(offset.x()), round(offset.y())),
                     surface.strip.row_size())
    small = row()
    assert small.top() == 50 + ANCHOR_INSET
    for size, factor in SIZES[1:]:
        follower.set_size(size)
        settle()
        r = row()
        assert surface.strip.scale() == factor
        assert r.width() > small.width() and r.height() > small.height()
        # Still centred on the window, the top edge the scaled inset inside it.
        assert abs(r.center().x() - (100 + 400)) <= 1
        assert abs(r.top() - (50 + ANCHOR_INSET * factor)) <= 0.5
        assert surface.is_presented()
        assert surface.size() == surface.strip.size()
    follower.set_size("small")
    settle()
    assert row() == small
    follower.shutdown()


# -- the controller ------------------------------------------------------------

def test_strips_are_medium_unless_told_otherwise(rig):
    _session, controller, _rects = rig(size=None)                  # no settings at all
    assert controller.follower.size() == "medium"
    assert controller.follower.surface("101").strip.scale() == 1.25
    _session, controller, _rects = rig(settings=Settings(), size=None)   # nothing stored
    assert controller.follower.surface("101").strip.scale() == 1.25


@pytest.mark.parametrize("size,factor", SIZES)
def test_size_comes_from_settings(rig, size, factor):
    settings = Settings(**{sk.FLOAT_STRIP_SIZE: size})
    _session, controller, _rects = rig(settings=settings, size=None)
    assert [s.strip.scale() for s in controller.follower.surfaces().values()] == [factor] * 4


def test_a_size_change_applies_live_to_every_strip_and_its_counters(rig):
    settings = Settings(**{sk.FLOAT_STRIP_SIZE: "small"})
    _session, controller, _rects = rig(settings=settings, size=None)
    pops = controller.popovers
    assert pops.counters_shown("101")                  # Flossbud's are locked on
    counters = pops.counters_surface("101")
    before = counters.size()
    right_click(controller, "102", L.KEYSET, 2)
    assert pops.open_tag("102") == "set:2"

    settings.set(sk.FLOAT_STRIP_SIZE, "large")
    settle()
    assert pops.open_tag("102") == ""                  # laid out for the old size: closed
    for wid in WIDS:
        surface = controller.follower.surface(wid)
        assert surface.strip.scale() == 1.5
        assert surface.is_presented()
    assert pops.counters_shown("101")
    assert counters.content.sizeHint().width() > before.width()
    # Still centred under the (larger) portrait and name.
    anchor = pops.anchor_rect("101", "identity")
    pill = counters.content.pill_rect().toAlignedRect().translated(counters.pos())
    assert abs(pill.center().x() - anchor.center().x()) <= 1
    assert pill.top() >= anchor.bottom()

    settings.set("something_else", "small")
    settle()
    assert controller.follower.size() == "large"
    settings.set(sk.FLOAT_STRIP_SIZE, "not a size")    # falls back to the default
    settle()
    assert controller.follower.size() == "medium"


def _on_screen(pops, wid):
    surface = pops.open_surface(wid)
    screen = QGuiApplication.primaryScreen().availableGeometry()
    return screen.contains(surface.geometry()), surface.geometry(), screen


def test_everything_that_hangs_off_a_large_strip_is_large_and_on_screen(rig):
    """Menus, the editor, the quick menu and the compact launcher take the
    strip's scale, and at 1.5 each still opens inside the screen."""
    keymaps = Keymaps(ttr=2)
    _session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    launcher = Launcher()
    controller._launcher = launcher
    launcher.changed.connect(controller._refresh_home_panel)
    controller.set_size("large")
    settle()
    pops = controller.popovers
    strip = controller.follower.surface("101").strip
    assert strip.scale() == 1.5

    def check(tag):
        assert pops.open_tag("101") == tag
        assert pops.open_content("101")._scale == 1.5, tag
        ok, geometry, screen = _on_screen(pops, "101")
        assert ok, (tag, geometry, screen)

    click(controller, "101", L.HOME)
    check("home")
    panel = pops.open_content("101")
    panel.set_view("launch")                              # the compact launcher
    pops.refit("101")
    settle()
    check("home")
    click(controller, "101", L.HOME)                      # closes
    right_click(controller, "101", L.PORTRAIT)
    check("toon")
    right_click(controller, "101", L.KEYSET, 1)
    check("set:1")
    editor = controller.open_editor("101", 1)
    settle()
    assert editor is not None
    check("edit:1")
    # The counters readout too.
    assert pops.counters_surface("101") is None or \
        pops.counters_surface("101").content._scale == 1.5


# -- the device pixel grid -----------------------------------------------------

def _on_grid(value, ds):
    return abs(value * ds - round(value * ds)) < 1e-6


@pytest.mark.parametrize("style", ["neon", "flat"])
@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 1.875])
@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_every_block_edge_is_a_whole_device_pixel(qapp, style, scale, dpr):
    strip = StripWidget()
    strip.devicePixelRatioF = lambda: dpr
    strip.set_style(style)
    strip.set_scale(scale)
    strip.set_model(FLOSSBUD.with_(home=True, name="A longer toon name",
                                   keysets=(1, 2, 3), hidden_sets=True))
    ds = scale * dpr
    assert strip.device_scale() == ds
    lay = strip.strip_layout()
    sizes = {}
    for block in lay.blocks:
        r = block.rect
        for edge in (r.left(), r.top(), r.right(), r.bottom()):
            assert _on_grid(edge, ds), (block.kind, block.number, r)
        sizes.setdefault(block.kind, set()).add((round(r.width() * ds), round(r.height() * ds)))
    # Equal blocks stay equal, and the gaps between them are all the same.
    assert len(sizes[L.KEYSET]) == 1 and len(sizes[L.SEPARATOR]) == 1
    keysets = [b.rect for b in lay.blocks if b.kind == L.KEYSET]
    gaps = {round((b.left() - a.right()) * ds) for a, b in zip(keysets, keysets[1:])}
    assert len(gaps) == 1 and gaps.pop() >= 1
    # The widget's own margin, so the row starts on a pixel as well.
    offset = strip.row_offset()
    assert _on_grid(offset.x() / scale, ds) and _on_grid(offset.y() / scale, ds)
    assert _on_grid(lay.width, ds) and _on_grid(lay.height, ds)


def test_at_scale_one_the_layout_is_the_design(qapp):
    strip = StripWidget()
    strip.set_model(FLOSSBUD)
    assert tokens.snapped_style(tokens.NEON_STYLE, 1.0) == tokens.NEON_STYLE
    assert strip.block_rect(L.ENABLE).size().toSize().width() == 28
    assert strip.row_offset().x() == MARGIN


def _render(strip, dpr):
    size = strip.sizeHint()
    image = QImage(round(size.width() * dpr), round(size.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(MAGENTA)
    p = QPainter(image)
    strip.render_strip(p)
    p.end()
    image.setDevicePixelRatio(1.0)
    return image


def _device_rect(strip, kind, number, dpr):
    r = strip.block_rect(kind, number)
    return QRect(round(r.x() * dpr), round(r.y() * dpr),
                 round(r.width() * dpr), round(r.height() * dpr))


@pytest.mark.parametrize("scale", [1.25, 1.5])
@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_block_edges_and_separators_paint_crisp(qapp, scale, dpr):
    """Flat fills are one opaque colour edge to edge, so a soft (blended)
    edge pixel is easy to tell: the first and last pixel of a block, on all
    four sides, are the fill itself; and a separator is a whole number of
    solid pixels wide."""
    strip = StripWidget()
    strip.devicePixelRatioF = lambda: dpr
    strip.set_style("flat")
    strip.set_scale(scale)
    strip.set_model(FLOSSBUD.with_(keysets=(1, 2, 3), active=3))
    image = _render(strip, dpr)
    fill = QColor(tokens.dk(tokens.set_color(2), 46))
    box = _device_rect(strip, L.KEYSET, 2, dpr)
    cx, cy = box.center().x(), box.center().y()
    for x, y in ((box.left(), cy), (box.right(), cy), (cx, box.top()), (cx, box.bottom())):
        assert image.pixelColor(x, y) == fill, (x, y, image.pixelColor(x, y).name())
    for x, y in ((box.left() - 1, cy), (box.right() + 1, cy),
                 (cx, box.top() - 1), (cx, box.bottom() + 1)):
        outside = image.pixelColor(x, y)                   # shadow over magenta
        assert outside.green() == 0 and outside.red() == outside.blue(), (x, y)

    # Neon: a 2 px border is a whole number of device pixels, both edges hard.
    strip.set_style("neon")
    image = _render(strip, dpr)
    box = _device_rect(strip, L.KEYSET, 3, dpr)            # lit: opaque border
    border = QColor(tokens.lt(tokens.set_color(3), 62))
    inner = QColor(tokens.set_color(3))
    width = round(tokens.snap(2.0, scale * dpr) * scale * dpr)
    row = [image.pixelColor(box.left() + i, box.center().y()) for i in range(width + 1)]
    assert all(c == border for c in row[:width]), [c.name() for c in row]
    assert row[width] == inner

    sep = next(b for b in strip.strip_layout().blocks if b.kind == L.SEPARATOR)
    r = strip._to_widget(sep.rect)
    x0, w = round(r.x() * dpr), round(r.width() * dpr)
    y = round(r.center().y() * dpr)
    white = [image.pixelColor(x0 + i, y) == QColor("#ffffff") for i in range(-1, w + 1)]
    assert white == [False] + [True] * w + [False]


# -- the drop shadow -----------------------------------------------------------

def _dark(colour):
    return 255 - colour.red()


@pytest.mark.parametrize("style", ["neon", "flat"])
@pytest.mark.parametrize("scale", [1.0, 1.25])
def test_every_block_casts_a_soft_shadow_below_it(qapp, style, scale):
    strip = StripWidget()
    strip.set_style(style)
    strip.set_scale(scale)
    strip.set_model(FLOSSBUD.with_(home=True, keep_alive=False, click_sync=False,
                                   keysets=(1, 2), active=2))
    image = _render(strip, 1.0)
    kinds = [(L.KEEP_ALIVE, 0), (L.KEYSET, 1), (L.ADD, 0)]
    if style == "flat":
        # In Neon the identity also wears its accent halo, over the shadow.
        kinds += [(L.PORTRAIT, 0), (L.NAME, 0)]
    for kind, number in kinds:
        r = strip.block_rect(kind, number)
        x = int(r.right() - 6 * scale) if kind == L.NAME else int(r.center().x())
        below = [image.pixelColor(x, int(r.bottom() + d * scale)) for d in (2, 5, 9)]
        above = image.pixelColor(x, int(r.top() - 5 * scale))
        for c in below:                                    # black over magenta
            assert c.green() == 0 and c.red() == c.blue(), (kind, c.name())
        assert _dark(below[0]) > _dark(below[1]) > _dark(below[2]) >= 0   # soft
        assert _dark(below[0]) >= 40, (kind, below[0].name())            # and visible
        assert _dark(below[1]) > _dark(above)              # it drops: more below
    # The shadow is never the darkest thing it could be (45 % black).
    assert max(_dark(image.pixelColor(x, y)) for x in range(0, image.width(), 3)
               for y in range(image.height() - int(8 * scale), image.height())) <= 255 * 0.46


def test_the_shadow_fits_the_margin_the_strip_already_had(qapp):
    """The row must not move for the shadow: it needs no more room than the
    Neon halos were given."""
    assert MARGIN == 14.0
    assert paint.SHADOW_REACH <= MARGIN
    strip = StripWidget()
    strip.set_model(FLOSSBUD)
    image = _render(strip, 1.0)
    edge = [image.pixelColor(x, image.height() - 1) for x in range(image.width())]
    assert all(_dark(c) <= 2 for c in edge)                # faded out by the edge


def test_the_shadow_is_under_the_halo_and_never_under_the_block(qapp, monkeypatch):
    model = FLOSSBUD.with_(hidden_sets=True)

    def render(style, shadows):
        strip = StripWidget()
        strip.set_style(style)
        strip.set_model(model.with_(enabled=style == "neon"))
        if not shadows:
            monkeypatch.setattr(paint.StripPainter, "shadow", lambda *a, **k: None)
        image = _render(strip, 1.0)
        monkeypatch.undo()
        return strip, image

    for style in ("neon", "flat"):
        strip, with_shadow = render(style, True)
        _strip, without = render(style, False)
        assert with_shadow != without
        # Inside every block, translucent ones included (Neon's dashed "+",
        # Flat's dimmed group), the pixels are what they were.
        for block in strip.strip_layout().blocks:
            r = strip._to_widget(block.rect).toAlignedRect().adjusted(3, 3, -3, -3)
            for x in range(r.left(), r.right() + 1, 2):
                for y in range(r.top(), r.bottom() + 1, 2):
                    if block.kind in (L.PORTRAIT, L.HOME):
                        dx, dy = x - r.center().x(), y - r.center().y()
                        if dx * dx + dy * dy > (r.width() / 2.0 - 1) ** 2:
                            continue
                    assert with_shadow.pixelColor(x, y) == without.pixelColor(x, y), (
                        style, block.kind, x, y)
    # Neon: just outside a lit block the halo's colour still shows through.
    strip, image = render("neon", True)
    lit = strip.block_rect(L.KEEP_ALIVE)
    halo = image.pixelColor(int(lit.center().x()), int(lit.top() - 2))
    assert halo.green() > 20                               # orange, not grey


def test_a_disabled_toons_blocks_keep_a_weaker_shadow(qapp):
    def below(model, kind, number=0):
        strip = StripWidget()
        strip.set_style("flat")
        strip.set_model(model)
        image = _render(strip, 1.0)
        r = strip.block_rect(kind, number)
        return _dark(image.pixelColor(int(r.center().x()), int(r.bottom() + 3)))

    on = below(FLOSSBUD, L.KEYSET, 2)
    off = below(FLOSSBUD.with_(enabled=False), L.KEYSET, 2)
    assert 0 < off < on
    assert off == pytest.approx(on * paint.SHADOW_DIMMED, abs=3)
    # The enable block itself never dims, nor does its shadow.
    assert below(FLOSSBUD.with_(enabled=False), L.ENABLE) == pytest.approx(
        below(FLOSSBUD, L.ENABLE), abs=1)


def test_a_click_on_a_shadow_goes_to_the_game(qapp):
    """The input region and the no-compositor shape are the blocks, exactly
    as before: a shadow is neither clickable nor shaped in as black."""
    strip = StripWidget()
    strip.set_model(FLOSSBUD.with_(home=True))
    blocks = [strip._to_widget(b.rect).toAlignedRect()
              for b in strip.strip_layout().blocks if b.kind in L.INTERACTIVE]
    assert strip.input_rects() == blocks
    shape = strip.shape_region()
    for block in strip.strip_layout().blocks:
        r = strip._to_widget(block.rect)
        under = QPoint(int(r.center().x()), int(r.bottom() + 3))
        assert not shape.contains(under), block.kind
        assert not any(rect.contains(under) for rect in strip.input_rects())
        assert strip._hit(under) is None

    surface = StripSurface(Strategy(), Backend(), 1.25)
    surface.set_model(FLOSSBUD)
    region = surface.input_region()
    r = surface.strip.block_rect(L.ENABLE).toAlignedRect()
    assert region.contains(r.center())
    assert not region.contains(QPoint(r.center().x(), r.bottom() + 4))
    surface.deleteLater()


def test_the_blur_is_built_once_per_box_and_scale(qapp):
    paint._shadow_tiles.clear()
    strip = StripWidget()
    strip.set_model(FLOSSBUD.with_(keysets=(1, 2, 3, 4)))
    _render(strip, 1.0)
    built = len(paint._shadow_tiles)
    # Portrait, name plate, the equal squares, the separators: a handful.
    assert 3 <= built <= 6
    for _ in range(3):
        _render(strip, 1.0)
    assert len(paint._shadow_tiles) == built
    strip.set_scale(1.25)
    _render(strip, 1.0)
    assert len(paint._shadow_tiles) == 2 * built


def test_a_number_block_drawn_elsewhere_has_no_shadow_unless_asked(qapp):
    def draw(**kw):
        image = QImage(60, 60, QImage.Format_ARGB32_Premultiplied)
        image.fill(MAGENTA)
        p = QPainter(image)
        paint.paint_number_block(p, QRectF(16, 16, 26, 26), 2, False, "flat", **kw)
        p.end()
        return image.pixelColor(29, 45)

    assert draw() == MAGENTA                               # a sheet's own panel
    assert _dark(draw(shadow=True)) > 20
