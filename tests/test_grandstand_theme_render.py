"""Grandstand widgets under the app's REAL stylesheet.

Every other grandstand test runs with no application stylesheet, so a plain
QWidget that inherits the app's `QWidget { background-color }` rule and paints
an opaque block over a custom-painted surface is invisible to them. This file
loads the actual theme and samples pixels.
"""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from tests._render_fixtures import complete_set
from utils import theme_manager
from utils.recent_toons import ToonRecord
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.account_sheet import PREVIEW_COL_W, AccountSheet
from utils.widgets.grandstand.card_shelf import CardShelf, SHELF_GAP
from utils.widgets.grandstand.draft import MODE_EDIT, AccountDraft
from utils.widgets.grandstand.game_selector import GameSelector
from utils.widgets.grandstand.hero_stage import COPY_LEFT, HERO_RADIUS, HeroStage
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.roster_card import (
    CARD_H, CARD_W, PORTRAIT, RosterCard,
)
from utils.widgets.grandstand.sheet import SheetShell
from utils.widgets.grandstand.toon_browser import FIGURE_H, FIGURE_TOP, ToonBrowser


def _distance(a, b):
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue()))


@contextmanager
def _temporary_theme(qapp, theme):
    """Apply one real theme and restore the preceding application state."""
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
        yield qapp, request.param


def _render(widget, w, h):
    widget.resize(w, h)
    widget.show()
    QApplication.instance().processEvents()
    pm = QPixmap(w, h)
    pm.fill(Qt.magenta)          # a colour nothing legitimate paints
    widget.render(pm)
    return pm.toImage()


def _entry(account_id):
    return RosterEntry(
        account_id=account_id, game="ttr", label=f"L{account_id}",
        username=f"u{account_id}", toon_name=f"T{account_id}", species="cat",
        dna="7400", accent="#4a8fe7", footer="Primary",
        portrait_mode="render", state="idle", message="", raw_error="",
    )


def test_hero_copy_container_does_not_paint_the_app_background(themed_app):
    """The copy column must reveal the custom-painted hero below it."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("ttr")
    img = _render(hero, 818, 232)
    # Inside copy, below every child: this is untouched hero artwork + scrim.
    probe = img.pixelColor(COPY_LEFT + 24, 200)
    base = gp.hero_base("ttr", theme == "dark")
    assert _distance(probe, base) < 60, (
        f"{theme}: copy container painted {probe.name()} over hero base "
        f"{base.name()}")
    hero.close()


def _label_probe(label, host):
    """A glyph-free pixel inside `label`, in `host` coordinates: the right
    end of the rect at mid-height. Every label probed here is left-aligned
    and narrower than its rect, so its right end holds no text."""
    origin = label.mapTo(host, label.rect().topLeft())
    return origin.x() + label.width() - 4, origin.y() + label.height() // 2


def _bare_pixel(host, widget, w, h, x, y):
    """The pixel at (x, y) with `widget` hidden but its layout slot kept, so
    nothing reflows onto the probe and the only difference is the widget's
    own paint."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    widget.hide()
    try:
        return _render(host, w, h).pixelColor(x, y)
    finally:
        widget.show()


@pytest.mark.parametrize("label_name", ["greeting", "names"])
def test_hero_labels_do_not_paint_the_app_background(themed_app, label_name):
    """The live defect one level below the copy container: QLabel is a
    styled-background widget, so without its own `background: transparent`
    the app's global QWidget rule paints each hero label as an opaque box
    (#1a1a1a dark, near-white light) over the art. The copy-container probe
    sits below both labels, which is why it never saw this."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("ttr")
    hero.set_party(["Flossbud"])           # a short names line: "Flossbud"
    label = getattr(hero, label_name)
    img = _render(hero, 818, 232)
    x, y = _label_probe(label, hero)
    text_w = label.fontMetrics().horizontalAdvance(label.text())
    assert text_w < label.width() - 8, "probe would land on a glyph"
    face = img.pixelColor(x, y)
    bare = _bare_pixel(hero, label, 818, 232, x, y)

    base = gp.hero_base("ttr", theme == "dark")
    assert bare != Qt.magenta and face != Qt.magenta
    assert _distance(face, bare) < 4, (
        f"{theme}: {label_name} painted {face.name()} over the hero's "
        f"{bare.name()} at ({x},{y})")
    assert _distance(face, base) < 60, (
        f"{theme}: {label_name} at ({x},{y}) reads {face.name()}, not the "
        f"hero base {base.name()}")
    hero.close()


def test_selector_logo_labels_do_not_paint_the_app_background(themed_app):
    """Same class of defect on the game selector: the logo is a pixmap
    QLabel with no stylesheet, so the global rule squared it off over the
    card art. Probe a corner of the label, clear of the centred logo."""
    _qapp, theme = themed_app
    selector = GameSelector()
    img = _render(selector, 818, 72)
    cards = [c for c in selector.children() if hasattr(c, "_logo")]
    assert len(cards) == 2
    for card in cards:
        logo = card._logo
        origin = logo.mapTo(selector, logo.rect().topLeft())
        x, y = origin.x() + 1, origin.y() + 1
        face = img.pixelColor(x, y)
        bare = _bare_pixel(selector, logo, 818, 72, x, y)
        assert bare != Qt.magenta and face != Qt.magenta
        assert _distance(face, bare) < 4, (
            f"{theme}: {card.game()} logo painted {face.name()} over the "
            f"card's {bare.name()} at ({x},{y})")
    selector.close()


def test_shelf_containers_do_not_paint_the_app_background(themed_app,
                                                           render_cache):
    """The head and gaps between cards must reveal the shelf panel."""
    _qapp, theme = themed_app
    shelf = CardShelf()
    shelf.set_entries([_entry("a"), _entry("b")])
    img = _render(shelf, 818, 300)
    panel = gp.panel(theme == "dark")["bg"]
    probes = {
        "head": img.pixelColor(400, 20),
        "strip": img.pixelColor(167, 162),
    }
    for area, probe in probes.items():
        assert _distance(probe, panel) < 10, (
            f"{theme}: shelf {area} painted {probe.name()} over panel "
            f"{panel.name()}")
    shelf.close()


def test_card_portrait_is_the_disk_render_under_the_real_stylesheet(
        themed_app, render_cache):
    """The migrated card, under the real theme: with a complete set on disk
    the portrait box shows the render's own pixels. A solid-colour PNG from
    `complete_set` makes the expected colour exact; a silhouette, the card
    wash or a styled child painting over the box would all read far from it,
    which the bare-card probe at the same pixel confirms."""
    _qapp, theme = themed_app
    _facade, store, _pf = render_cache
    expected = QColor("#ff0000")
    x, y = CARD_W // 2, 12 + PORTRAIT // 2       # centre of the portrait box

    bare = RosterCard()
    bare.set_entry(_entry("a"))                   # nothing on disk: silhouette
    without = _render(bare, CARD_W, CARD_H).pixelColor(x, y)
    bare.close()
    assert without != Qt.magenta
    assert _distance(without, expected) > 100, (
        f"{theme}: probe at ({x},{y}) is not discriminating")

    complete_set(store, "ttr", "Ta", "7400", expected.name())
    card = RosterCard()
    card.set_entry(_entry("a"))
    face = _render(card, CARD_W, CARD_H).pixelColor(x, y)
    card.close()
    assert _distance(face, expected) < 4, (
        f"{theme}: portrait box painted {face.name()}, not the disk render "
        f"{expected.name()}")
    assert card.portrait_tier() == "current"


def test_themed_app_fixture_restores_global_state(qapp):
    """Everything apply_theme touches must be back to its prior value."""
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    theme = "light" if before_marker == "dark" else "dark"

    with _temporary_theme(qapp, theme):
        assert theme_manager._APPLIED_THEME == theme

    assert qapp.styleSheet() == before_sheet
    assert qapp.palette() == before_palette
    assert theme_manager._APPLIED_THEME == before_marker


# Probes across the Clash art, clear of the copy column and the crew slots:
# top, middle and bottom of the stage at three widths.
_CC_ART_PROBES = [(x, y) for x in (450, 600, 780) for y in (40, 120, 220)]


def test_clash_hero_reads_warm_not_blue_teal(themed_app):
    """Handoff §4.1b: the Clash skyline is natively blue-teal, and the
    horizontal scrim alone leaves it so. The warm overlay must be painted,
    so every sampled art pixel reads red-dominant; the TTR stage, which has
    no warm layer, must still read blue — the overlay is a Clash treatment,
    not a global tint."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("cc")
    img = _render(hero, 818, 232)
    for x, y in _CC_ART_PROBES:
        probe = img.pixelColor(x, y)
        assert (probe.red() - probe.blue() >= 10
                and probe.red() > probe.green()), (
            f"{theme}: cc hero at ({x},{y}) painted {probe.name()}, not warm")
    hero.set_game("ttr")
    img = _render(hero, 818, 232)
    for x, y in _CC_ART_PROBES:
        probe = img.pixelColor(x, y)
        assert probe.blue() > probe.red(), (
            f"{theme}: ttr hero at ({x},{y}) painted {probe.name()}, warmed")
    hero.close()


def test_disabled_play_renders_translucent_under_the_real_stylesheet(
        themed_app):
    """The alpha-loss defect painted a solid white Play with an invisible
    label. Under the real stylesheet the disabled button must let the hero
    show through: its face is a white wash over the backdrop, so it reads
    lighter than the bare backdrop at the same pixel yet nowhere near opaque
    white. Both bounds matter — "not white" alone also holds for a button
    that paints no face at all."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("ttr")
    hero.set_party([])
    assert hero.play_enabled() is False
    button = hero.play_button
    img = _render(hero, 818, 232)
    origin = button.mapTo(hero, button.rect().topLeft())
    # Inside the border, left of the label: face colour only.
    x, y = origin.x() + 8, origin.y() + button.height() // 2
    face = img.pixelColor(x, y)

    button.hide()
    bare = _render(hero, 818, 232).pixelColor(x, y)
    button.show()

    white = QColor("#ffffff")
    assert bare != Qt.magenta and face != Qt.magenta
    assert _distance(face, white) > 300, (
        f"{theme}: disabled Play face painted {face.name()}")
    assert _distance(face, QColor("#000000")) > _distance(bare, QColor("#000000")), (
        f"{theme}: disabled Play face {face.name()} is no lighter than the "
        f"bare backdrop {bare.name()} — nothing was painted")
    hero.close()


def test_disabled_play_keeps_its_translucency(qapp):
    """`.name()` drops alpha; all disabled Play colours must carry ARGB."""
    hero = HeroStage()
    hero.set_party([])
    assert hero.play_enabled() is False
    style = hero.play_button.styleSheet()
    colours = gp.play_button(False, True)
    for name in ("bg", "ink", "border"):
        expected = colours[name].name(QColor.HexArgb)
        assert expected in style
        assert len(expected) == 9
        assert expected.lower() != "#ffffffff"
    hero.close()


def test_the_hero_art_does_not_fill_the_corners(themed_app):
    """Live 2026-09-21: the hero's corners were square. paintEvent drew the
    rounded base, then clipped to the plain rect and painted the art over it
    — square. Rendered alone into a transparent image (`QWidget.render` with
    DrawChildren only, since `grab()` fills the window background and the hero
    is opaque RGB32 to it), nothing may land outside the rounded outline. Under
    the real stylesheet that also means the hero's own styled background: the
    global `QWidget { background-color }` rule would otherwise paint a square
    block (the page colour, or in light mode the hero's OWN copy of the page
    gradient) under the rounded base."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("ttr")
    hero.resize(818, 232)
    hero.show()
    QApplication.instance().processEvents()
    img = QImage(hero.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    hero.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    w, h = hero.width(), hero.height()
    for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
        px = img.pixelColor(x, y)
        assert px.alpha() == 0, (
            f"{theme}: hero painted {px.name(QColor.HexArgb)} at ({x},{y}), "
            "outside its rounded outline")
    inside = img.pixelColor(HERO_RADIUS + 2, HERO_RADIUS + 2)
    assert inside.alpha() == 255, f"{theme}: inside the outline is not opaque"
    hero.close()


# ── sub-project C: the sheet and the browser under the real stylesheet ──────

def _toon(name, dna):
    return ToonRecord(name, "ttr", dna, 137, None, "cat", None)


def _sheet(theme):
    shell = SheetShell()
    body = AccountSheet(shell)
    shell.set_body(body)
    shell.apply_theme(theme == "dark")
    draft = AccountDraft(id="a", game="ttr", mode=MODE_EDIT, label="La",
                         username="ua", password="pw", keyring_has_password=True)
    body.open(draft, [_toon("Ta", "7400")], "Ta", _entry("a"))
    shell.set_header("Account · La", "Toontown Rewritten · changes apply to this account only")
    shell.set_cross_link("✏ Customize appearance")
    shell.set_note("1 toon discovered")
    return shell, body


def _browser(theme, toons):
    browser = ToonBrowser()
    browser.apply_theme(theme == "dark")
    browser.open("ttr", "a", "La", toons, "Ta")
    return browser


def test_sheet_containers_do_not_paint_the_app_background(themed_app, render_cache):
    """The header, the preview column and the space around the body are
    plain containers and labels: under the real stylesheet each must show the
    sheet surface, not a square of page colour (bg_app is #1a1a1a dark and
    #f8fafc light; the surface is #252525 / #ffffff — both discriminable)."""
    _qapp, theme = themed_app
    shell, body = _sheet(theme)
    img = _render(shell, 818, 520)
    surface = gp.sheet_surface(theme == "dark")["bg"]
    origin = body.preview.mapTo(shell, QPoint(0, 0))
    fields_origin = body.fields.mapTo(shell, QPoint(0, 0))
    label_block = body.label_field.geometry()          # relative to `fields`
    probes = {
        # left of the card, inside the 184 px preview column
        "inside the preview column": (origin.x() - 9, origin.y() + 20),
        # the 26 px gap between the column and the fields (the body itself)
        "column gap": (origin.x() + CARD_W + (PREVIEW_COL_W - CARD_W) // 2 + 13,
                       origin.y() + 20),
        # the 16 px gap between the two grid columns (the fields container)
        "fields column gap": (fields_origin.x() + label_block.right() + 8,
                              fields_origin.y() + label_block.top() + 30),
        "below the body": (origin.x() + CARD_W // 2, origin.y() + CARD_H + 40),
        "header": (shell.width() // 2, 16),
    }
    for area, (x, y) in probes.items():
        probe = img.pixelColor(x, y)
        assert probe != Qt.magenta
        assert _distance(probe, surface) < 6, (
            f"{theme}: sheet {area} painted {probe.name()} over surface "
            f"{surface.name()} at ({x},{y})")
    shell.close()


def test_sheet_preview_shows_the_disk_render_under_the_real_stylesheet(
        themed_app, render_cache):
    _qapp, theme = themed_app
    _facade, store, _pf = render_cache
    expected = QColor("#ff0000")
    complete_set(store, "ttr", "Ta", "7400", expected.name())
    shell, body = _sheet(theme)
    img = _render(shell, 818, 520)
    origin = body.preview.mapTo(shell, QPoint(0, 0))
    x, y = origin.x() + CARD_W // 2, origin.y() + 12 + PORTRAIT // 2
    face = img.pixelColor(x, y)
    assert _distance(face, expected) < 4, (
        f"{theme}: preview portrait painted {face.name()}, not the disk render")
    assert body.frow_portrait.pixmap() is not None
    shell.close()


def test_browser_containers_do_not_paint_the_app_background(themed_app, render_cache):
    _qapp, theme = themed_app
    browser = _browser(theme, [_toon("Ta", "7400"), _toon("Tb", "7401")])
    img = _render(browser, 818, 320)
    surface = gp.sheet_surface(theme == "dark")["bg"]
    first = browser.cards()[0]
    origin = first.mapTo(browser, QPoint(0, 0))
    probes = {
        "gap between cards": (origin.x() + CARD_W + SHELF_GAP // 2,
                              origin.y() + CARD_H // 2),
        "header": (browser.width() // 2, 16),
        "strip margin": (origin.x() + CARD_W // 2, origin.y() - 8),
    }
    for area, (x, y) in probes.items():
        probe = img.pixelColor(x, y)
        assert probe != Qt.magenta
        assert _distance(probe, surface) < 6, (
            f"{theme}: browser {area} painted {probe.name()} over surface "
            f"{surface.name()} at ({x},{y})")
    browser.close()


def test_browser_empty_state_does_not_paint_the_app_background(themed_app, render_cache):
    _qapp, theme = themed_app
    browser = _browser(theme, [])
    img = _render(browser, 818, 320)
    surface = gp.sheet_surface(theme == "dark")["bg"]
    origin = browser.empty_title.mapTo(browser, QPoint(0, 0))
    x, y = origin.x() - 12, origin.y() + browser.empty_title.height() // 2
    probe = img.pixelColor(x, y)
    assert _distance(probe, surface) < 6, (
        f"{theme}: empty state painted {probe.name()} over {surface.name()}")
    browser.close()


def test_browser_card_shows_the_waving_render_under_the_real_stylesheet(
        themed_app, render_cache):
    _qapp, theme = themed_app
    _facade, store, _pf = render_cache
    expected = QColor("#00ff00")
    complete_set(store, "ttr", "Ta", "7400", expected.name())
    browser = _browser(theme, [_toon("Ta", "7400")])
    img = _render(browser, 818, 320)
    card = browser.card_for("Ta")
    origin = card.mapTo(browser, QPoint(0, 0))
    # An 8x8 PNG scales to 124x124 and sits at the BOTTOM of the 132 box
    # (rows 18..141): probe 4 px above the box's floor, which a top-anchored
    # figure (rows 10..133) would leave to the card wash.
    x = origin.x() + CARD_W // 2
    y = origin.y() + FIGURE_TOP + FIGURE_H - 4
    face = img.pixelColor(x, y)
    assert _distance(face, expected) < 4, (
        f"{theme}: figure painted {face.name()}, not the disk render")
    assert card.portrait_pixmap() is not None
    browser.close()
