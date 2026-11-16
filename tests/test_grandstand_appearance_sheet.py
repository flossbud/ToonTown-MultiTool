"""AppearanceSheet: the editor body (design note 2026-11-16; handoff §4.2,
§4.3, §4.6).

Every test mounts the editor inside a host widget and shows it, so a control
that is merely constructed but never visible cannot pass for one that works.
"""
import math
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QRawFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from tests._render_fixtures import real_png
from utils.recent_toons import ToonRecord
from utils.rendition_poses import POSE_NAMES
from utils.widgets.grandstand import appearance_controls as controls
from utils.widgets.grandstand import appearance_sheet as sheet_module
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.appearance_controls import (
    CANVAS_D, POSE_TILE, SWITCHER_EMPTY, SWITCHER_NOTE, SWITCHER_W,
    WELL_H, WELL_W, switcher_heading,
)
from utils.widgets.grandstand.appearance_draft import (
    FILL_GRADIENT, FILL_SOLID, POSE_LABELS, AppearanceDraft,
)
from utils.widgets.grandstand.appearance_sheet import (
    ACCENT_CLEAR, AUTOMATIC, BACKDROP_CLEAR, CROSS_LINK, STAGE_W,
    AppearanceSheet, note_for, subtitle_for, title_for,
)

DNA = "74050102013b1b301bb31b12001212010400113800020000016000000000020800"
SKY = {"accent": "#4a8fe7", "portrait": {
    "gradient": {"start": "#82a4ff", "end": "#002a97"},
    "pattern": {"name": "stars", "color": "#ffffff"}}}

# One distinct colour per pose, so a test can tell which render is showing.
POSE_COLOURS = {pose: QColor.fromHsv(int(index * 360 / len(POSE_NAMES)), 255, 255).name()
                for index, pose in enumerate(POSE_NAMES)}


def _land_poses(store, game, name, dna):
    store.note_dna(game, name, dna)
    for pose in store.poses:
        real_png(store.path_for(game, name, dna, pose), POSE_COLOURS[pose])
        assert store.mark_landed(game, name, dna, pose)
    assert store.promote_if_complete(game, name)


def _rec(name="Flossbud", dna=DNA, species="dog", game="ttr", laff=137):
    return ToonRecord(name, game, dna, laff, 137, species, None)


def _draft(entry=None, rec=None, game="ttr", account_name="flossbud"):
    rec = _rec() if rec is None else rec
    return AppearanceDraft.for_record(
        account_id="a1", account_name=account_name, game=game,
        rec=rec or None, entry=entry or {})


def _no_toon_draft(game="ttr"):
    return AppearanceDraft.for_record(
        account_id="a4", account_name="crimsondeku", game=game, rec=None, entry={})


@pytest.fixture
def host(qapp):
    widget = QWidget()
    widget.resize(828, 520)
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def _mount(host, draft, toons=None, primary=None):
    editor = AppearanceSheet(host)
    editor.setGeometry(0, 0, host.width(), host.height())
    editor.open(draft, [_rec()] if toons is None else toons, primary)
    host.show()
    QApplication.instance().processEvents()
    return editor


def _pixel(pixmap):
    return pixmap.toImage().pixelColor(0, 0)


# ── copy ────────────────────────────────────────────────────────────────────

def test_header_and_footer_copy():
    d = _draft()
    assert title_for(d) == "Appearance · Flossbud"
    assert subtitle_for(d) == ("Toontown Rewritten · this look follows Flossbud "
                               "wherever the launcher shows it")
    assert note_for(d) == "Saves to toon_customizations.json · ttr::Flossbud"
    assert CROSS_LINK == "⚙ Account settings"


def test_copy_for_an_account_with_no_toon_names_the_account():
    d = _no_toon_draft()
    assert title_for(d) == "Appearance · crimsondeku"
    assert subtitle_for(d) == "Toontown Rewritten · no toon discovered yet"
    assert note_for(d) == "Nothing to save until a toon is discovered"


def _user_visible_constants():
    for module in (sheet_module, controls):
        for name in dir(module):
            value = getattr(module, name)
            if name.isupper() and isinstance(value, str):
                yield f"{module.__name__}.{name}", value
            elif name.isupper() and isinstance(value, (list, tuple)):
                for item in value:
                    for part in (item if isinstance(item, (list, tuple)) else [item]):
                        if isinstance(part, str):
                            yield f"{module.__name__}.{name}", part
    for label in POSE_LABELS.values():
        yield "POSE_LABELS", label
    for look in gp.LOOKS:
        yield "LOOKS", look[0]


def test_no_em_dash_reaches_the_user():
    offenders = [name for name, text in _user_visible_constants() if "—" in text]
    assert offenders == []


def test_every_glyph_shown_is_in_the_bundled_font(qapp):
    """No emoji or symbol the bundled DejaVu Sans cannot draw: on a machine
    without a fallback font it would be an empty box."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    font = QRawFont(os.path.join(root, "assets", "fonts", "DejaVuSans.ttf"), 12)
    assert font.isValid()
    missing = {(name, ch) for name, text in _user_visible_constants()
               for ch in text if ord(ch) > 126 and not font.supportsCharacter(ord(ch))}
    assert missing == set()
    for ch in "×°":                                   # the two slider readouts
        assert font.supportsCharacter(ord(ch))


# ── open: the controls show the stored look ─────────────────────────────────

def test_open_seeds_every_control_from_the_draft(host):
    entry = dict(SKY, pose="portrait-grin")
    entry["portrait"] = dict(SKY["portrait"], transform={
        "zoom": 1.49, "offset_x": 0.1, "offset_y": -0.05, "rotate": 12})
    editor = _mount(host, _draft(entry))
    assert editor.pill.name_text() == "Flossbud"
    assert editor.fill_chips.value() == FILL_GRADIENT
    assert editor.fill_chips.chip(FILL_GRADIENT).isChecked() is True
    assert editor.wells["g_start"].color() == "#82a4ff"
    assert editor.wells["g_end"].color() == "#002a97"
    assert editor.gradient_bar.stops() == ("#82a4ff", "#002a97")
    assert editor.pattern_chips.value() == "stars"
    assert editor.wells["pat_color"].color() == "#ffffff"
    assert editor.wells["accent"].color() == "#4a8fe7"
    assert editor.accent_readout.full_text() == "#4a8fe7"
    assert editor.looks.selected() == 0                       # Sky
    assert editor.pose_strip.selected() == "portrait-grin"
    assert editor.pose_header.note_text() == "Grin · Multitoon and the radial menu"
    assert editor.zoom_row.slider.value() == 149
    assert editor.zoom_row.value.text() == "1.49×"
    assert editor.turn_row.slider.value() == 12
    assert editor.turn_row.value.text() == "12°"
    assert editor.canvas.look() == entry
    assert editor.draft().is_dirty() is False                 # showing is not editing


def test_the_editor_is_two_columns_with_the_handoff_canvas(host):
    editor = _mount(host, _draft())
    assert editor.stage.width() == STAGE_W == 272
    assert (editor.canvas.width(), editor.canvas.height()) == (CANVAS_D, CANVAS_D) == (240, 240)
    stage_right = editor.stage.mapTo(host, QPoint(editor.stage.width(), 0)).x()
    controls_left = editor.controls.mapTo(host, QPoint(0, 0)).x()
    assert controls_left - stage_right == 20
    assert editor.scope.text() == "the look follows the toon, not the account"
    assert (editor.surprise.text(), editor.reset.text()) == ("Surprise me", "Reset all")


# ── looks ───────────────────────────────────────────────────────────────────

def test_a_look_sets_five_values_in_one_click_and_lights_itself(host):
    editor = _mount(host, _draft())
    assert editor.looks.selected() is None
    ember = editor.looks.swatches[5]
    QTest.mouseClick(ember, Qt.LeftButton)
    d = editor.draft()
    assert (d.fill, d.g_start, d.g_end) == (FILL_GRADIENT, "#e74a4a", "#7a1410")
    assert (d.pat_name, d.pat_color, d.accent) == ("chevrons", "#e6d35a", "#e74a4a")
    assert editor.looks.selected() == 5
    assert ember.is_selected() is True
    # The canvas paints the same dict a Save would store.
    assert editor.canvas.look() == d.preview_entry()
    assert editor.scope_dot.color() == QColor("#e74a4a")
    assert [s.name for s in editor.looks.swatches] == [look[0] for look in gp.LOOKS]


def test_a_hand_edit_unlights_the_look(host):
    editor = _mount(host, _draft(SKY))
    assert editor.looks.selected() == 0
    QTest.mouseClick(editor.pattern_chips.chip(None), Qt.LeftButton)
    assert editor.looks.selected() is None


def test_look_swatches_carry_the_accounts_own_toon(host, render_cache):
    _facade, store, _pf = render_cache
    _land_poses(store, "ttr", "Flossbud", DNA)
    editor = _mount(host, _draft())
    for swatch in editor.looks.swatches:
        assert swatch.art() is not None
        assert _pixel(swatch.art()) == QColor(POSE_COLOURS["head"])


# ── backdrop ────────────────────────────────────────────────────────────────

def test_solid_shows_one_well_and_gradient_shows_the_bar_and_swap(host):
    editor = _mount(host, _draft({"portrait": {"color": "#56c856"}}))
    solid = (editor.wells["color"], editor.color_readout)
    gradient = (editor.wells["g_start"], editor.gradient_bar,
                editor.wells["g_end"], editor.swap_button)
    assert all(w.isVisible() for w in solid)
    assert not any(w.isVisible() for w in gradient)
    assert editor.color_readout.full_text() == "#56c856"

    QTest.mouseClick(editor.fill_chips.chip(FILL_GRADIENT), Qt.LeftButton)
    assert editor.draft().fill == FILL_GRADIENT
    assert all(w.isVisible() for w in gradient)
    assert not any(w.isVisible() for w in solid)

    start, end = editor.draft().g_start, editor.draft().g_end
    QTest.mouseClick(editor.swap_button, Qt.LeftButton)
    assert (editor.draft().g_start, editor.draft().g_end) == (end, start)
    assert editor.gradient_bar.stops() == (end, start)

    QTest.mouseClick(editor.fill_chips.chip(FILL_SOLID), Qt.LeftButton)
    assert editor.draft().fill == FILL_SOLID
    assert editor.draft().color == "#56c856"                  # kept across the detour
    assert editor.draft().is_dirty() is False


def test_an_unset_backdrop_reads_automatic(host):
    editor = _mount(host, _draft())
    assert editor.wells["color"].color() is None              # the hatch
    assert editor.color_readout.full_text() == AUTOMATIC


def test_wells_are_the_handoff_size(host):
    editor = _mount(host, _draft())
    for well in editor.wells.values():
        assert (well.width(), well.height()) == (WELL_W, WELL_H) == (44, 30)


# ── pattern ─────────────────────────────────────────────────────────────────

def test_the_pattern_well_appears_only_with_a_pattern(host):
    editor = _mount(host, _draft())
    assert [c.text() for c in editor.pattern_chips.chips()] == [
        "None", "Dots", "Chevrons", "Stars"]
    assert editor.wells["pat_color"].isVisible() is False
    QTest.mouseClick(editor.pattern_chips.chip("dots"), Qt.LeftButton)
    assert editor.draft().pat_name == "dots"
    assert editor.wells["pat_color"].isVisible() is True
    assert editor.pattern_readout.full_text() == "#ffffff"
    QTest.mouseClick(editor.pattern_chips.chip(None), Qt.LeftButton)
    assert editor.draft().pat_name is None
    assert editor.wells["pat_color"].isVisible() is False


def test_a_pattern_from_the_old_customizer_keeps_a_chip(host):
    editor = _mount(host, _draft({"portrait": {
        "pattern": {"name": "hearts", "color": "#e74ab0"}}}))
    assert [c.text() for c in editor.pattern_chips.chips()][-1] == "Hearts"
    assert editor.pattern_chips.value() == "hearts"
    # A different toon's look drops the extra chip again.
    editor.open(_draft(), [_rec()], None)
    assert [c.text() for c in editor.pattern_chips.chips()] == [
        "None", "Dots", "Chevrons", "Stars"]


# ── accent ──────────────────────────────────────────────────────────────────

def test_an_unset_accent_says_what_automatic_resolves_to(host):
    editor = _mount(host, _draft())
    assert editor.wells["accent"].color() is None
    assert editor.accent_readout.full_text() == "game accent · #4a8fe7"
    assert editor.scope_dot.color() == QColor("#4a8fe7")


# ── colour wells: one popover, on demand ────────────────────────────────────

def test_a_well_opens_the_twelve_swatches_and_a_pick_sets_the_colour(host):
    editor = _mount(host, _draft(SKY))
    popover = editor.swatch_popover
    assert popover.isVisible() is False
    well = editor.wells["g_start"]
    QTest.mouseClick(well, Qt.LeftButton)
    assert popover.isVisible() is True and well.is_open() is True
    assert [s.hex for s in popover.swatches()] == list(gp.SWATCHES)
    assert popover.clear_button.isVisible() is False          # nothing to unset
    # Below the well, 7 px clear of it.
    assert popover.mapTo(host, QPoint(0, 0)).y() == (
        well.mapTo(host, QPoint(0, 0)).y() + WELL_H + 7)
    pick = next(s for s in popover.swatches() if s.hex == "#e74a4a")
    QTest.mouseClick(pick, Qt.LeftButton)
    assert editor.draft().g_start == "#e74a4a"
    assert popover.isVisible() is False and well.is_open() is False
    assert editor.open_well() is None


def test_only_one_well_is_open_at_a_time(host):
    editor = _mount(host, _draft(SKY))
    QTest.mouseClick(editor.wells["g_start"], Qt.LeftButton)
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    assert editor.open_well() is editor.wells["accent"]
    assert editor.wells["g_start"].is_open() is False
    assert editor.swatch_popover.anchor() is editor.wells["accent"]
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)   # its own well toggles
    assert editor.swatch_popover.isVisible() is False


def test_one_well_at_a_time_holds_for_keyboard_activation_too(host):
    """Space on a focused well is a click with no mouse press, so the
    outside-click filter never sees it: the editor itself must close the
    well that was open."""
    editor = _mount(host, _draft(SKY))
    editor.wells["g_start"].click()
    editor.wells["g_end"].click()
    assert editor.open_well() is editor.wells["g_end"]
    assert editor.wells["g_start"].is_open() is False
    assert editor.swatch_popover.anchor() is editor.wells["g_end"]


def test_the_popover_marks_the_current_colour(host):
    editor = _mount(host, _draft({"accent": "#56c856"}))
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    lit = [s.hex for s in editor.swatch_popover.swatches() if s.is_selected()]
    assert lit == ["#56c856"]


def test_the_accent_popover_can_return_to_the_game_accent(host):
    editor = _mount(host, _draft({"accent": "#56c856"}))
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    clear = editor.swatch_popover.clear_button
    assert clear.isVisible() is True and clear.text() == ACCENT_CLEAR == "Use game accent"
    QTest.mouseClick(clear, Qt.LeftButton)
    assert editor.draft().accent is None
    assert editor.accent_readout.full_text() == "game accent · #4a8fe7"
    assert "accent" not in editor.draft().apply_to({"accent": "#56c856"})


def test_the_solid_popover_can_return_to_the_automatic_backdrop(host):
    editor = _mount(host, _draft({"portrait": {"color": "#56c856"}}))
    QTest.mouseClick(editor.wells["color"], Qt.LeftButton)
    clear = editor.swatch_popover.clear_button
    assert clear.isVisible() is True and clear.text() == BACKDROP_CLEAR
    QTest.mouseClick(clear, Qt.LeftButton)
    assert editor.draft().color is None
    assert editor.draft().apply_to({"portrait": {"color": "#56c856"}}) == {}


def test_a_click_anywhere_else_closes_the_popover_and_still_lands(host):
    editor = _mount(host, _draft())
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    assert editor.swatch_popover.isVisible() is True
    QTest.mouseClick(editor.pattern_chips.chip("dots"), Qt.LeftButton)
    assert editor.swatch_popover.isVisible() is False
    assert editor.draft().pat_name == "dots"                  # the click was not eaten
    assert editor.draft().accent is None


def test_escape_closes_an_open_popover(host):
    editor = _mount(host, _draft())
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    QTest.keyClick(editor.wells["accent"], Qt.Key_Escape)
    assert editor.swatch_popover.isVisible() is False


def test_the_outside_click_filter_lives_only_while_a_popover_is_open(host):
    editor = _mount(host, _draft())
    assert editor._watching is False
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    assert editor._watching is True
    editor.hide()                                             # e.g. a surface switch
    assert editor._watching is False
    assert editor.swatch_popover.isVisible() is False
    assert editor.open_well() is None


# ── pose strip (handoff §4.6 render) ────────────────────────────────────────

def test_thirteen_poses_with_human_names(host):
    editor = _mount(host, _draft())
    tiles = editor.pose_strip.tiles
    assert [t.pose for t in tiles] == list(POSE_NAMES)
    assert [t.label for t in tiles] == [
        "Portrait", "Delighted", "Grin", "Thinking", "Surprised", "Sleepy",
        "Falling", "Birthday", "Head", "Waving", "Crying", "Cake topper",
        "Laff meter"]
    assert tiles[0].width() == POSE_TILE == 68
    assert editor.pose_header.label_text() == "Pose"
    assert editor.pose_strip.isVisible() is True
    assert editor.standin.isVisible() is False and editor.waiting.isVisible() is False


def test_each_tile_and_the_canvas_show_their_own_render(host, render_cache):
    _facade, store, _pf = render_cache
    _land_poses(store, "ttr", "Flossbud", DNA)
    editor = _mount(host, _draft())
    for tile in editor.pose_strip.tiles:
        assert _pixel(tile.pixmap()) == QColor(POSE_COLOURS[tile.pose])
    assert _pixel(editor.canvas.art()) == QColor(POSE_COLOURS["portrait"])

    waving = editor.pose_strip.tile("waving")
    editor.pose_strip.reveal("waving")
    QApplication.instance().processEvents()
    QTest.mouseClick(waving, Qt.LeftButton)
    assert editor.draft().pose == "waving"
    assert waving.is_selected() is True
    assert editor.pose_strip.selected() == "waving"
    assert _pixel(editor.canvas.art()) == QColor(POSE_COLOURS["waving"])
    assert editor.pose_header.note_text() == "Waving · Multitoon and the radial menu"


def test_only_a_pose_change_reads_a_render(host, render_cache, monkeypatch):
    """Repaint discipline (handoff §5): colour and framing edits restyle the
    canvas in place. Nothing but a pose change may go back to the cache."""
    facade, store, _pf = render_cache
    _land_poses(store, "ttr", "Flossbud", DNA)
    editor = _mount(host, _draft())
    reads = []
    real = facade.pixmap_for

    def counting(game, name, pose):
        reads.append(pose)
        return real(game, name, pose)

    monkeypatch.setattr(facade, "pixmap_for", counting)
    QTest.mouseClick(editor.looks.swatches[2], Qt.LeftButton)
    QTest.mouseClick(editor.fill_chips.chip(FILL_SOLID), Qt.LeftButton)
    QTest.mouseClick(editor.pattern_chips.chip("stars"), Qt.LeftButton)
    editor.zoom_row.slider.setValue(180)
    editor.turn_row.slider.setValue(-20)
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    QTest.mouseClick(editor.swatch_popover.swatches()[0], Qt.LeftButton)
    assert reads == []
    QTest.mouseClick(editor.pose_strip.tile("portrait-grin"), Qt.LeftButton)
    assert reads == ["portrait-grin"]


def test_a_landed_render_fills_its_tile_and_the_canvas_and_never_clears(
        host, render_cache, monkeypatch):
    facade, store, _pf = render_cache
    editor = _mount(host, _draft())
    assert editor.canvas.art() is None
    assert editor.pose_strip.tile("portrait").pixmap() is None
    _land_poses(store, "ttr", "Flossbud", DNA)
    facade.render_landed.emit("ttr", "Flossbud", "portrait")
    assert _pixel(editor.canvas.art()) == QColor(POSE_COLOURS["portrait"])
    assert _pixel(editor.pose_strip.tile("portrait").pixmap()) == QColor(
        POSE_COLOURS["portrait"])
    # Someone else's landing changes nothing.
    facade.render_landed.emit("ttr", "Pepper", "portrait")
    facade.render_landed.emit("cc", "Flossbud", "portrait")
    assert _pixel(editor.canvas.art()) == QColor(POSE_COLOURS["portrait"])
    # Nor does a landing the store cannot serve yet (a newer outfit's file):
    # what is showing is still what the store would serve.
    monkeypatch.setattr(facade, "pixmap_for", lambda game, name, pose: None)
    facade.render_landed.emit("ttr", "Flossbud", "portrait")
    assert _pixel(editor.canvas.art()) == QColor(POSE_COLOURS["portrait"])
    assert _pixel(editor.pose_strip.tile("portrait").pixmap()) == QColor(
        POSE_COLOURS["portrait"])


# ── framing ─────────────────────────────────────────────────────────────────

def test_the_sliders_write_zoom_and_turn(host):
    editor = _mount(host, _draft())
    assert (editor.zoom_row.slider.minimum(), editor.zoom_row.slider.maximum()) == (50, 300)
    assert (editor.turn_row.slider.minimum(), editor.turn_row.slider.maximum()) == (-180, 180)
    editor.zoom_row.slider.setValue(150)
    editor.turn_row.slider.setValue(-45)
    d = editor.draft()
    assert (d.zoom, d.rotate) == (1.5, -45.0)
    assert editor.zoom_row.value.text() == "1.50×"
    assert editor.turn_row.value.text() == "-45°"
    assert editor.canvas.look()["portrait"]["transform"] == {
        "zoom": 1.5, "offset_x": 0.0, "offset_y": 0.0, "rotate": -45.0}


def _drag(canvas, dx, dy):
    centre = QPoint(CANVAS_D // 2, CANVAS_D // 2)
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, centre)
    QTest.mouseMove(canvas, centre + QPoint(dx, dy))
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, centre + QPoint(dx, dy))


def _painted_shift(draft):
    """Where production's badge puts the portrait for this framing: rotate
    about the centre, then offset by zoomed circle fractions."""
    angle = math.radians(draft.rotate)
    x = draft.off_x * CANVAS_D * draft.zoom
    y = draft.off_y * CANVAS_D * draft.zoom
    return (x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle))


@pytest.mark.parametrize("zoom, rotate", [(1.0, 0), (2.0, 0), (1.0, 90), (1.5, -40)])
def test_a_drag_keeps_the_portrait_under_the_pointer(host, zoom, rotate):
    editor = _mount(host, _draft({"portrait": {"transform": {
        "zoom": zoom, "offset_x": 0.0, "offset_y": 0.0, "rotate": rotate}}}))
    assert editor.canvas.is_draggable() is True
    _drag(editor.canvas, 48, -24)
    shift = _painted_shift(editor.draft())
    assert shift[0] == pytest.approx(48, abs=1.0)
    assert shift[1] == pytest.approx(-24, abs=1.0)


def test_a_drag_at_neutral_framing_is_the_delta_over_the_diameter(host):
    editor = _mount(host, _draft())
    _drag(editor.canvas, 24, -12)
    assert editor.draft().off_x == pytest.approx(0.1, abs=0.005)
    assert editor.draft().off_y == pytest.approx(-0.05, abs=0.005)


def test_a_drag_is_clamped_to_the_resolvers_range(host):
    editor = _mount(host, _draft({"portrait": {"transform": {
        "zoom": 0.5, "offset_x": 0.9, "offset_y": 0.0, "rotate": 0}}}))
    _drag(editor.canvas, 100, 0)
    assert editor.draft().off_x == 1.0


# ── species mode (handoff §4.6) ─────────────────────────────────────────────

def _clash(host, entry=None):
    rec = ToonRecord("Cogsworth", "cc", "", 80, 80, "DOG", None)
    draft = AppearanceDraft.for_record(account_id="c1", account_name="cogsworth",
                                       game="cc", rec=rec, entry=entry or {})
    return _mount(host, draft, [rec], "Cogsworth")


def test_corporate_clash_shows_portrait_art_and_no_pose_control(host):
    editor = _clash(host)
    assert editor.pose_strip.isVisible() is False
    assert editor.waiting.isVisible() is False
    assert editor.standin.isVisible() is True
    assert editor.pose_header.label_text() == "Portrait art"
    assert editor.pose_header.note_text() == "no render service for this game"
    assert editor.standin.title.text() == "Dog race icon"
    body = editor.standin.body.text()
    assert body.startswith("Corporate Clash publishes no render service, so "
                           "Cogsworth cannot be drawn from the game.")
    assert "the dog race icon it ships with" in body
    assert editor.tag.isVisible() is True and editor.tag.text() == "DOG RACE ICON"
    assert editor.accent_readout.full_text() == "game accent · #f26d21"


def test_corporate_clash_offers_no_framing_because_nothing_draws_it(host):
    """Production's Clash badge ignores portrait.transform. The editor must
    not write values no surface paints."""
    editor = _clash(host)
    assert editor.sliders.isVisible() is False
    assert editor.hint.isVisible() is False
    assert editor.canvas.is_draggable() is False
    _drag(editor.canvas, 40, 40)
    editor.zoom_row.slider.setValue(200)
    assert (editor.draft().zoom, editor.draft().off_x) == (1.0, 0.0)
    assert editor.draft().is_dirty() is False
    assert "framing" not in editor.standin.body.text()


def test_corporate_clash_draws_the_race_icon_inset(host):
    editor = _clash(host)
    assert editor.canvas.art() is not None                    # the shipped dog icon
    assert editor.canvas._art_scale == 0.8                    # ART_INSET
    assert all(s.art() is not None for s in editor.looks.swatches)


def test_a_clash_icon_chosen_in_the_old_customizer_is_the_one_drawn(host):
    from utils import cc_race_assets
    editor = _clash(host, {"icon_stem": "bear"})
    assert editor.canvas.art().cacheKey() == cc_race_assets.load_race_pixmap("bear").cacheKey()


# ── waiting: no toon discovered (handoff §4.6) ──────────────────────────────

def test_an_account_with_no_toon_explains_and_edits_nothing(host):
    editor = _mount(host, _no_toon_draft(), [], None)
    assert editor.pill.name_text() == "crimsondeku"
    assert editor.pose_strip.isVisible() is False
    assert editor.standin.isVisible() is False
    assert editor.waiting.isVisible() is True
    assert editor.waiting.text() == (
        "Poses need a toon render. Launch this account once so the launcher "
        "can discover a toon, then every pose becomes selectable here.")
    assert editor.pose_header.note_text() == "no toon discovered yet"
    # A look is stored per toon: with none there is nothing to edit.
    assert editor.controls.isEnabled() is False
    assert editor.surprise.isEnabled() is False and editor.reset.isEnabled() is False
    assert editor.canvas.is_draggable() is False
    QTest.mouseClick(editor.looks.swatches[0], Qt.LeftButton)
    assert editor.draft().is_dirty() is False


def test_a_named_toon_with_no_dna_is_editable_but_has_no_poses(host):
    rec = _rec(name="Nodna", dna="")
    editor = _mount(host, _draft(rec=rec), [rec], "Nodna")
    assert editor.pose_strip.isVisible() is False
    assert editor.waiting.isVisible() is True
    assert "Nodna" in editor.waiting.text()
    assert editor.controls.isEnabled() is True
    QTest.mouseClick(editor.looks.swatches[0], Qt.LeftButton)
    assert editor.draft().matching_look() == 0


# ── the subject row and the toon switcher (handoff §4.3) ────────────────────

def _three():
    return [_rec("Flossbud", DNA, "dog", laff=137),
            _rec("Pepper Fizzlebounce", "7401", "cat", laff=62),
            _rec("Sir Wackyhopper", "7402", "duck", laff=64)]


def test_the_pill_opens_the_switcher_listing_the_accounts_toons(host):
    editor = _mount(host, _draft(), _three(), "Flossbud")
    switcher = editor.switcher
    assert switcher.isVisible() is False
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert switcher.isVisible() is True
    assert switcher.width() == SWITCHER_W == 300
    assert switcher.heading_text() == "3 toons on flossbud"
    assert [r.toon for r in switcher.rows()] == [
        "Flossbud", "Pepper Fizzlebounce", "Sir Wackyhopper"]
    assert [r.meta for r in switcher.rows()] == [
        "Dog · Laff 137", "Cat · Laff 62", "Duck · Laff 64"]
    current = switcher.row_for("Flossbud")
    assert current.is_current() is True and current.isEnabled() is False
    assert switcher.row_for("Sir Wackyhopper").isEnabled() is True
    assert switcher.note_text() == SWITCHER_NOTE
    assert switcher.is_warning() is False
    # Below the pill, overlaying the columns: nothing reflowed.
    assert switcher.mapTo(host, QPoint(0, 0)).y() == (
        editor.pill.mapTo(host, QPoint(0, 0)).y() + 38)
    QTest.mouseClick(editor.pill, Qt.LeftButton)              # the pill toggles
    assert switcher.isVisible() is False


def test_the_switcher_warns_when_the_look_has_unsaved_edits(host):
    """Built at open time, so the warning reflects the edits made since."""
    editor = _mount(host, _draft(), _three(), "Flossbud")
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert editor.switcher.is_warning() is False
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    QTest.mouseClick(editor.looks.swatches[3], Qt.LeftButton)
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert editor.switcher.is_warning() is True
    assert editor.switcher.note_text() == (
        "Switching discards the unsaved changes to Flossbud's look.")


def test_picking_a_toon_asks_the_owner_and_writes_nothing_here(host):
    editor = _mount(host, _draft(), _three(), "Flossbud")
    seen = []
    editor.toon_switch_requested.connect(seen.append)
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    QTest.mouseClick(editor.switcher.row_for("Sir Wackyhopper"), Qt.LeftButton)
    assert seen == ["Sir Wackyhopper"]
    assert editor.switcher.isVisible() is False
    assert editor.draft().toon_name == "Flossbud"             # the owner re-opens


def test_the_current_toon_is_inert(host):
    editor = _mount(host, _draft(), _three(), "Flossbud")
    seen = []
    editor.toon_switch_requested.connect(seen.append)
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    QTest.mouseClick(editor.switcher.row_for("Flossbud"), Qt.LeftButton)
    assert seen == []


def test_rename_ghosts_collapse_in_the_switcher(host):
    toons = [_rec("Katsuro", "7405", "cat"), _rec("Blue Cat", "7405", "cat"),
             _rec("Flossbud", DNA, "dog")]
    editor = _mount(host, _draft(), toons, "Flossbud")
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert [r.toon for r in editor.switcher.rows()] == ["Katsuro", "Flossbud"]
    assert editor.switcher.heading_text() == "2 toons on flossbud"


def test_the_switcher_explains_an_account_with_no_toons(host):
    editor = _mount(host, _no_toon_draft(), [], None)
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert editor.switcher.isVisible() is True
    assert editor.switcher.rows() == []
    assert editor.switcher.heading_text() == "Toons on crimsondeku"
    assert editor.switcher.note_text() == SWITCHER_EMPTY
    assert switcher_heading(1, "x") == "1 toon on x"


def test_a_click_outside_closes_the_switcher(host):
    editor = _mount(host, _draft(), _three(), "Flossbud")
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    QTest.mouseClick(editor.canvas, Qt.LeftButton)
    assert editor.switcher.isVisible() is False


def test_the_switcher_and_a_well_are_never_open_together(host):
    editor = _mount(host, _draft(), _three(), "Flossbud")
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    assert editor.switcher.isVisible() is True
    assert editor.swatch_popover.isVisible() is False
    assert editor.open_well() is None


# ── surprise me and reset all (handoff §5) ──────────────────────────────────

def test_surprise_me_rolls_a_look_a_pose_and_a_framing(host):
    editor = _mount(host, _draft())
    editor.set_random(random.Random(11))
    QTest.mouseClick(editor.surprise, Qt.LeftButton)
    d = editor.draft()
    assert d.matching_look() is not None
    assert editor.looks.selected() == d.matching_look()
    assert d.pose in POSE_NAMES[:8]
    assert editor.pose_strip.selected() == d.pose
    assert 1.0 <= d.zoom <= 1.6
    assert editor.zoom_row.slider.value() == round(d.zoom * 100)
    assert editor.canvas.look() == d.preview_entry()


def test_reset_all_returns_every_control_to_unset(host):
    entry = dict(SKY, pose="waving", body="#123456")
    editor = _mount(host, _draft(entry))
    QTest.mouseClick(editor.reset, Qt.LeftButton)
    d = editor.draft()
    assert (d.accent, d.pose, d.fill, d.color, d.pat_name) == (
        None, "portrait", FILL_SOLID, None, None)
    assert editor.looks.selected() is None
    assert editor.pose_strip.selected() == "portrait"
    assert editor.fill_chips.value() == FILL_SOLID
    assert editor.color_readout.full_text() == AUTOMATIC
    assert d.apply_to(entry) == {"body": "#123456"}           # reset is not a wipe


# ── discipline ──────────────────────────────────────────────────────────────

def test_every_label_under_the_editor_sets_its_own_font_size(host):
    """setFont() loses to the app stylesheet's `QWidget { font-size: 12pt }`,
    so each label must carry font-size in its own stylesheet."""
    editor = _mount(host, _draft(SKY), _three(), "Flossbud")
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    for label in editor.findChildren(QLabel):
        if label.pixmap() is not None and not label.pixmap().isNull():
            continue                                          # an icon, no text
        assert "font-size" in label.styleSheet(), label.text()


def test_every_button_in_the_editor_is_reachable_by_keyboard(host):
    editor = _mount(host, _draft(SKY))
    chain = editor.tab_chain()
    assert chain[0] is editor.pill
    for button in editor.controls.findChildren(QAbstractButton):
        if button.isVisibleTo(editor):
            assert button.focusPolicy() != Qt.NoFocus, button
    assert editor.zoom_row.slider in chain and editor.turn_row.slider in chain


def _grab(widget):
    return widget.grab().toImage()


def _has_colour(image, colour, slack=30):
    return any(
        abs(image.pixelColor(x, y).red() - colour.red())
        + abs(image.pixelColor(x, y).green() - colour.green())
        + abs(image.pixelColor(x, y).blue() - colour.blue()) <= slack
        for x in range(image.width()) for y in range(image.height()))


def test_opening_puts_focus_in_the_editor_without_lighting_a_control(host, qapp):
    editor = _mount(host, _draft({"portrait": {"color": "#1a1d29"}}))
    host.activateWindow()
    editor.focus_first()
    qapp.processEvents()
    assert qapp.focusWidget() is editor                   # Esc and Enter reach the shell
    ring = gp.focus_ring(True)
    for control in (editor.wells["color"], editor.looks.swatches[1],
                    editor.pose_strip.tiles[1], editor.swap_button):
        assert not _has_colour(_grab(control), ring), control
    QTest.keyClick(editor, Qt.Key_Tab)
    assert qapp.focusWidget() is editor.pill              # Tab enters at the subject


@pytest.mark.parametrize("pick", ["well", "look", "pose"])
def test_a_painted_control_shows_keyboard_focus(host, qapp, pick):
    """A control reachable by Tab must say where the focus is."""
    editor = _mount(host, _draft({"portrait": {"color": "#1a1d29"}}))
    control = {"well": editor.wells["color"], "look": editor.looks.swatches[1],
               "pose": editor.pose_strip.tiles[1]}[pick]
    host.activateWindow()
    ring = gp.focus_ring(True)
    assert not _has_colour(_grab(control), ring)
    control.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    assert qapp.focusWidget() is control
    assert _has_colour(_grab(control), ring)


def test_a_mouse_click_does_not_leave_a_focus_ring(host, qapp):
    editor = _mount(host, _draft())
    host.activateWindow()
    for control in (editor.wells["accent"], editor.looks.swatches[2],
                    editor.pose_strip.tiles[0], editor.pill,
                    editor.fill_chips.chip(FILL_GRADIENT)):
        QTest.mouseClick(control, Qt.LeftButton)
        assert qapp.focusWidget() is not control, control


def test_a_mouse_wheel_drives_the_pose_strip_sideways(host, qapp):
    """Thirteen tiles, about seven on screen: a plain wheel must reach the
    rest. Qt would send it to a vertical bar that has no range."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    editor = _mount(host, _draft())
    bar = editor.pose_strip.scroll.horizontalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0
    assert editor.pose_strip.fade.isVisible() is True     # more to the right

    def wheel(dy):
        viewport = editor.pose_strip.scroll.viewport()
        pos = QPointF(40, 30)
        event = QWheelEvent(pos, QPointF(viewport.mapToGlobal(pos.toPoint())),
                            QPoint(0, 0), QPoint(0, dy), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        qapp.sendEvent(viewport, event)
        return event.isAccepted()

    assert wheel(-120) is True
    assert bar.value() == 120
    for _ in range(20):
        wheel(-120)
    assert bar.value() == bar.maximum()
    assert editor.pose_strip.fade.isVisible() is False    # the end: no fade
    assert wheel(-120) is False                           # handed on to the body
