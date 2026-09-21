"""Tests for the in-app customization panel (overlay + _Panel).

These cover the same scenarios as the deleted
test_toon_customization_dialog.py but build a ToonCustomizationOverlay
and exercise its embedded _Panel via the same public API."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeManager:
    def __init__(self):
        self._store: dict[tuple[str, str], dict] = {}

    def get(self, game, name):
        return dict(self._store.get((game, name), {}))

    def set(self, game, name, customization):
        if not customization:
            self._store.pop((game, name), None)
        else:
            self._store[(game, name)] = dict(customization)

    def clear(self, game, name):
        self._store.pop((game, name), None)


def _build(qapp, manager=None, game="ttr", existing=None, dna=None):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    mgr = manager or _FakeManager()
    if existing:
        mgr.set(game, "Flossbud", existing)
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(
        slot=0, game=game, toon_name="Flossbud", manager=mgr,
        dna=dna, skin_color=QColor("#d9a04e") if game == "cc" else None,
        auto_stem="dog" if game == "cc" else None,
    )
    return overlay._panel, mgr, overlay, parent


def test_panel_constructs(qapp):
    panel, _, _, _parent = _build(qapp)
    assert "Customize Flossbud" in panel.title_label.text()


def test_ttr_has_no_icon_section(qapp):
    panel, _, _, _parent = _build(qapp, game="ttr")
    assert "Icon" not in panel.section_names()


def test_cc_has_race_gallery_in_right_pane(qapp):
    """CC panel has no nav sections; the race gallery lives in the right pane."""
    from utils.widgets.race_icon_grid import RaceIconGridWidget
    panel, _, _, _parent = _build(qapp, game="cc")
    assert panel.section_names() == []
    grid = panel.findChild(RaceIconGridWidget)
    assert grid is not None


def test_save_writes_draft_to_manager(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_accent("#56c856")
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#56c856"}


def test_cancel_does_not_touch_manager(qapp):
    panel, mgr, overlay, _parent = _build(qapp, existing={"accent": "#abcdef"})
    panel.set_accent("#56c856")
    overlay.close_and_discard()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#abcdef"}


def test_reset_all_empties_draft(qapp):
    panel, _, _, _parent = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    panel.reset_all()
    assert panel.draft() == {}


def test_reset_all_clears_silhouette_visual_state_on_pose_section(qapp, monkeypatch, tmp_path):
    """Reset all must also clear the inline framing view's silhouette swatch
    state. Without this, the swatch row retains the old color and the next
    chip click re-writes silhouette back into the cleared draft."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {
            "outline": {"color": "#ff0000", "width": "thick"},
            "shadow":  {"color": "#000000", "softness": "strong"},
        }},
    })
    sec = panel.section("Toon")
    # Inline framing view is always built when DNA is set.
    panel.reset_all()
    # Draft is empty.
    assert panel.draft() == {}
    # Framing view's pickers are at default.
    adjust = sec._adjust_view
    assert adjust._sil_outline_color_row.current() is None
    assert adjust._sil_shadow_color_row.current() is None


def test_draft_loaded_from_existing(qapp):
    panel, _, _, _parent = _build(qapp, existing={"accent": "#56c856"})
    assert panel.draft() == {"accent": "#56c856"}


def test_set_body(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_body("#101020")
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}


def test_set_accent_to_none_removes_field(qapp):
    panel, mgr, overlay, _parent = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    panel.set_accent(None)
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}


def test_set_portrait_color(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_portrait_color("#d9a04e")
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#d9a04e"}}


def test_set_portrait_color_to_none_removes_color(qapp):
    panel, mgr, overlay, _parent = _build(qapp, existing={"portrait": {"color": "#d9a04e"}})
    panel.set_portrait_color(None)
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_set_gradient(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_portrait_gradient({"start": "#ff0000", "end": "#00ff00"})
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"gradient": {"start": "#ff0000", "end": "#00ff00"}}
    }


def test_set_pattern(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_portrait_pattern("dots", "#ffffff")
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"pattern": {"name": "dots", "color": "#ffffff"}}
    }


def test_clear_pattern(qapp):
    panel, mgr, overlay, _parent = _build(qapp, existing={
        "portrait": {"pattern": {"name": "dots", "color": "#fff000"}}
    })
    panel.set_portrait_pattern(None, None)
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_portrait_combines_color_pattern(qapp):
    panel, mgr, overlay, _parent = _build(qapp)
    panel.set_portrait_color("#d9a04e")
    panel.set_portrait_pattern("stripes_diag", "#101020")
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {
            "color": "#d9a04e",
            "pattern": {"name": "stripes_diag", "color": "#101020"},
        }
    }


def test_cc_icon_section_initial_selection(qapp):
    """When CC entry has icon_stem, the Icon section reflects it."""
    panel, _, _, _parent = _build(
        qapp, game="cc",
        existing={"icon_stem": "dog"},
    )
    sec = panel.section("Icon")
    assert sec.selected_stem() == "dog"


def test_cc_icon_section_save(qapp):
    panel, mgr, overlay, _parent = _build(qapp, game="cc")
    panel.set_icon_stem("dog")
    overlay.close_and_save()
    assert mgr.get("cc", "Flossbud") == {"icon_stem": "dog"}


def test_cc_icon_set_to_none_removes_field(qapp):
    panel, mgr, overlay, _parent = _build(qapp, game="cc", existing={"icon_stem": "dog"})
    panel.set_icon_stem(None)
    overlay.close_and_save()
    assert mgr.get("cc", "Flossbud") == {}


def test_pose_tile_initial_state(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    tile = _PoseTile("portrait-grin")
    assert tile.pose == "portrait-grin"
    assert tile.is_selected() is False
    assert tile.has_pixmap() is False


def test_pose_tile_set_pixmap(qapp):
    from PySide6.QtGui import QPixmap
    from utils.widgets.toon_customization_sections import _PoseTile
    pm = QPixmap(32, 32)
    pm.fill()
    tile = _PoseTile("waving")
    tile.set_pixmap(pm)
    assert tile.has_pixmap() is True


def test_pose_tile_set_selected_toggles(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    tile = _PoseTile("head")
    tile.set_selected(True)
    assert tile.is_selected() is True
    tile.set_selected(False)
    assert tile.is_selected() is False


def test_pose_tile_click_emits_pose(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_sections import _PoseTile
    tile = _PoseTile("portrait-sleep")
    spy = QSignalSpy(tile.clicked_pose)
    press = QMouseEvent(
        QMouseEvent.MouseButtonPress,
        QPointF(10, 10),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    tile.mousePressEvent(press)
    assert spy.count() == 1
    assert spy.at(0)[0] == "portrait-sleep"


def test_ttr_panel_has_toon_section_first(qapp):
    panel, _, _, _parent = _build(qapp, game="ttr")
    names = panel.section_names()
    assert names[0] == "Toon"
    # Order: Toon, Card, Portrait
    assert names == ["Toon", "Card", "Portrait"]


def test_cc_panel_has_no_toon_section(qapp):
    panel, _, _, _parent = _build(qapp, game="cc")
    assert "Toon" not in panel.section_names()


def test_set_pose_updates_draft_and_save_persists(qapp):
    panel, mgr, overlay, _parent = _build(qapp, dna="dna-test-123")
    panel.set_pose("portrait-grin")
    assert panel.draft().get("pose") == "portrait-grin"
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud").get("pose") == "portrait-grin"


def test_set_pose_to_default_removes_field(qapp):
    panel, mgr, overlay, _parent = _build(qapp, existing={"pose": "portrait-grin"}, dna="dna-test-123")
    panel.set_pose("portrait")  # back to default
    overlay.close_and_save()
    # "portrait" is the default; it does NOT need to be stored.
    saved = mgr.get("ttr", "Flossbud")
    assert "pose" not in saved


def test_pose_section_dna_none_shows_placeholder(qapp):
    """When the slot has no DNA, the Toon section shows a placeholder
    message instead of the tile grid."""
    panel, _, _, _parent = _build(qapp, game="ttr")  # dna=None
    sec = panel.section("Toon")
    assert sec.has_placeholder() is True
    assert sec.tiles() == []


def test_pose_section_with_dna_builds_13_tiles(qapp):
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test-123")
    sec = panel.section("Toon")
    assert sec.has_placeholder() is False
    tiles = sec.tiles()
    assert len(tiles) == 13
    poses = {t.pose for t in tiles}
    assert "portrait" in poses
    assert "portrait-grin" in poses


def test_pose_tiles_fill_from_disk_and_refresh_invalidates(render_cache, qapp):
    from tests._render_fixtures import complete_set
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    assert all(t._pixmap is not None for t in sec._tiles)
    sec._on_refresh_clicked()
    assert store.current_dna("ttr", "Hiro") is None          # current dropped
    assert store.candidate_dna("ttr", "Hiro") == "dna1"      # re-queued
    assert pf.pending_count + pf.in_flight_count == len(store.poses)


def test_refresh_button_invalidates_this_toon_in_the_cache(render_cache, qapp):
    """The section's refresh button is the one sanctioned cache write: it
    goes through ToonRenders.invalidate for the identity the overlay passed
    in, drops the current set and re-queues every pose. Tiles fall back to
    their own pending state until the poses re-land."""
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Flossbud", "dna-test-123")
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test-123")
    sec = panel.section("Toon")
    assert all(t.has_pixmap() for t in sec.tiles())
    sec.click_refresh()
    assert store.current_dna("ttr", "Flossbud") is None
    assert store.candidate_dna("ttr", "Flossbud") == "dna-test-123"
    assert pf.pending_count + pf.in_flight_count == len(store.poses)
    assert all(t.is_loading() for t in sec.tiles())


def test_pose_tiles_fill_as_the_refreshed_set_re_lands(render_cache, qapp):
    """After a refresh with no previous look to fall back on, the toon has no
    complete set at all, so each re-landed pose shows as it arrives (tier
    "candidate") instead of every tile shimmering until 13/13. A landing
    fills only its own tile; landings and promotions for other toons are
    ignored; the promotion fills whatever is left."""
    from tests._render_fixtures import complete_set, real_png
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    sec._on_refresh_clicked()
    assert all(t.is_loading() for t in sec.tiles())
    by_pose = {t.pose: t for t in sec.tiles()}
    real_png(store.path_for("ttr", "Hiro", "dna1", "portrait"))    # one pose re-lands
    assert store.mark_landed("ttr", "Hiro", "dna1", "portrait")
    facade.render_landed.emit("ttr", "Other", "portrait")
    assert all(t.is_loading() for t in sec.tiles()), "another toon's landing filled a tile"
    facade.render_landed.emit("ttr", "Hiro", "portrait")
    assert by_pose["portrait"].has_pixmap(), "the re-landed pose was withheld"
    assert all(t.is_loading() for t in sec.tiles() if t.pose != "portrait")
    for pose in store.poses:                                   # the rest re-lands silently
        if pose != "portrait":
            real_png(store.path_for("ttr", "Hiro", "dna1", pose))
            assert store.mark_landed("ttr", "Hiro", "dna1", pose)
    assert store.promote_if_complete("ttr", "Hiro")
    facade.set_promoted.emit("ttr", "Other")
    assert all(t.is_loading() for t in sec.tiles() if t.pose != "portrait"), \
        "another toon's promotion filled the tiles"
    facade.set_promoted.emit("ttr", "Hiro")
    assert all(t.has_pixmap() for t in sec.tiles())


def _pixel(pixmap):
    return pixmap.toImage().pixelColor(0, 0)


def test_refresh_repaints_every_tile_from_the_previous_look_at_once(render_cache, qapp):
    """A refresh drops the current set; with a previous look on disk the
    store serves that immediately, so every tile repaints from it instead of
    shimmering. A re-landed pose of the refreshed set is a candidate file
    (not servable): the tile keeps the previous look, and the framing view
    stays on the selected tile's pixmap. Another toon's landing is ignored."""
    from tests._render_fixtures import complete_set, real_png
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    complete_set(store, "ttr", "Hiro", "dna2", "#0000ff")      # dna2 current, dna1 previous
    sec = _PoseSection("ttr", "Hiro", "dna2", "portrait")
    assert all(_pixel(t._pixmap) == QColor("#0000ff") for t in sec.tiles())
    sec._on_refresh_clicked()
    assert store.current_dna("ttr", "Hiro") is None             # dna2's files are gone
    assert all(t.has_pixmap() for t in sec.tiles()), "a tile went dark although the store still serves"
    assert all(_pixel(t._pixmap) == QColor("#ff0000") for t in sec.tiles())   # the previous look
    by_pose = {t.pose: t for t in sec.tiles()}
    assert sec._adjust_view._preview.pixmap() is by_pose["portrait"]._pixmap
    real_png(store.path_for("ttr", "Hiro", "dna2", "portrait"), "#00ff00")    # dna2 re-lands one pose
    assert store.mark_landed("ttr", "Hiro", "dna2", "portrait")
    facade.render_landed.emit("ttr", "Other", "portrait")
    facade.render_landed.emit("ttr", "Hiro", "portrait")
    assert all(_pixel(t._pixmap) == QColor("#ff0000") for t in sec.tiles()), "a candidate file was shown"
    assert sec._adjust_view._preview.pixmap() is by_pose["portrait"]._pixmap


def test_refresh_keeps_tiles_the_store_did_not_remove(render_cache, qapp):
    """A refresh while a newer outfit is already downloading touches nothing
    in the store (that download IS the fresh art the user wants), so every
    tile keeps the picture the store still serves. Blanking them would lose
    the current look for nothing."""
    from tests._render_fixtures import complete_set
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    store.note_dna("ttr", "Hiro", "dna2")                        # candidate pending, nothing landed
    sec = _PoseSection("ttr", "Hiro", "dna2", "portrait")
    assert all(_pixel(t._pixmap) == QColor("#ff0000") for t in sec.tiles())
    sec._on_refresh_clicked()
    assert store.current_dna("ttr", "Hiro") == "dna1"            # the store deferred to the candidate
    assert store.candidate_dna("ttr", "Hiro") == "dna2"
    assert all(t.has_pixmap() for t in sec.tiles()), "refresh blanked a tile the store never removed"
    assert all(_pixel(t._pixmap) == QColor("#ff0000") for t in sec.tiles())
    assert _pixel(sec._adjust_view._preview.pixmap()) == QColor("#ff0000")


def test_a_landing_that_is_not_yet_servable_keeps_the_tiles(render_cache, qapp):
    """A landing only ever adds a file. When that file belongs to an outfit
    the store cannot serve yet, the tile keeps what it shows: the picture on
    screen is still the best the section has. Only a promotion replaces it.
    (The toon keeps a
    complete set here -- with one lost file, so the read genuinely misses --
    because a toon with no complete set at all IS served its candidate.)"""
    from tests._render_fixtures import complete_set, real_png
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    by_pose = {t.pose: t for t in sec.tiles()}
    assert _pixel(by_pose["portrait"]._pixmap) == QColor("#ff0000")
    os.remove(store.path_for("ttr", "Hiro", "dna1", "portrait"))  # lost; nothing told the section
    store.note_dna("ttr", "Hiro", "dna2")          # ...and the toon changed outfit meanwhile
    real_png(store.path_for("ttr", "Hiro", "dna2", "portrait"), "#00ff00")
    assert store.mark_landed("ttr", "Hiro", "dna2", "portrait")
    assert facade.pixmap_for("ttr", "Hiro", "portrait") is None   # landed, not servable
    facade.render_landed.emit("ttr", "Hiro", "portrait")
    assert by_pose["portrait"].has_pixmap(), "a landing cleared the tile"
    assert _pixel(by_pose["portrait"]._pixmap) == QColor("#ff0000")
    assert _pixel(sec._adjust_view._preview.pixmap()) == QColor("#ff0000")
    complete_set(store, "ttr", "Hiro", "dna2", "#00ff00")
    facade.set_promoted.emit("ttr", "Hiro")
    assert all(_pixel(t._pixmap) == QColor("#00ff00") for t in sec.tiles())
    assert sec._adjust_view._preview.pixmap() is by_pose["portrait"]._pixmap


def test_a_landing_that_fills_the_selected_tile_fills_the_framing_view(render_cache, qapp):
    """The current set has a hole for the selected pose (the facade deletes
    a file its decoder rejects and re-fetches it). While it is missing the
    tile pends and the framing view has nothing; when it lands, the tile
    fills and the framing view shows that same pixmap."""
    from tests._render_fixtures import complete_set, real_png
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    os.remove(store.path_for("ttr", "Hiro", "dna1", "portrait"))
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    by_pose = {t.pose: t for t in sec.tiles()}
    assert by_pose["portrait"].is_loading()
    assert by_pose["waving"].has_pixmap()
    assert sec._adjust_view._preview.pixmap() is None
    real_png(store.path_for("ttr", "Hiro", "dna1", "portrait"))
    assert store.mark_landed("ttr", "Hiro", "dna1", "portrait")
    facade.render_landed.emit("ttr", "Hiro", "portrait")
    assert by_pose["portrait"].has_pixmap()
    assert sec._adjust_view._preview.pixmap() is by_pose["portrait"]._pixmap


def test_pose_section_with_an_empty_toon_name_never_touches_the_cache(render_cache, qapp, monkeypatch):
    """An empty name is not a toon: a facade read keyed on it would create
    `toons/<game>/toon/manifest.json`. The section mirrors the preview's
    guard and never connects to or reads the facade without a name."""
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    asked = []
    monkeypatch.setattr(facade, "pixmap_for", lambda *a: asked.append(a))
    sec = _PoseSection("ttr", "", "dna1", "portrait")
    assert sec._renders is None
    assert len(sec.tiles()) == 13 and all(t.is_loading() for t in sec.tiles())
    sec._on_refresh_clicked()
    sec._on_tile_retry_requested("portrait")
    facade.render_landed.emit("ttr", "", "portrait")
    facade.set_promoted.emit("ttr", "")
    assert asked == []
    manifests = [os.path.join(d, f) for d, _dirs, files in os.walk(store.toons_root())
                 for f in files if f == "manifest.json"]
    assert manifests == []
    assert pf.pending_count + pf.in_flight_count == 0            # nothing queued either


def test_reopening_the_overlay_leaves_no_facade_connections_behind(render_cache, qapp):
    """The facade is a process-wide singleton and the panel rebuilds its
    preview and pose section on every open_for (deleteLater, never close()).
    Every connection to the facade is a bound method of the widget, which
    PySide drops when the C++ object dies: the receiver count is a constant
    +2 (preview + section) across re-opens and returns to baseline after the
    overlay is torn down. A lambda connection would grow this forever and
    call into dead widgets."""
    from PySide6.QtCore import QCoreApplication, QEvent, SIGNAL
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Flossbud", "dna-test-123")

    def landed():
        return pf.receivers(SIGNAL("render_landed(QString,QString,QString)"))

    def promoted():
        return pf.receivers(SIGNAL("set_promoted(QString,QString)"))

    def flush():
        for _ in range(5):
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            qapp.processEvents()

    base_l, base_p = landed(), promoted()
    panel, mgr, overlay, parent = _build(qapp, game="ttr", dna="dna-test-123")
    flush()
    assert (landed() - base_l, promoted() - base_p) == (2, 2)
    overlay.open_for(slot=0, game="ttr", toon_name="Flossbud", manager=mgr, dna="dna-test-123")
    flush()
    assert (landed() - base_l, promoted() - base_p) == (2, 2), "the torn-down pair leaked"
    assert all(t.has_pixmap() for t in overlay._panel.section("Toon").tiles())
    overlay.deleteLater()
    parent.deleteLater()
    flush()
    assert (landed() - base_l, promoted() - base_p) == (0, 0)
    facade.render_landed.emit("ttr", "Flossbud", "portrait")   # nothing left to reach
    facade.set_promoted.emit("ttr", "Flossbud")


def test_pose_tiles_show_pending_state_when_nothing_is_on_disk(render_cache, qapp):
    """Nothing on disk is not a cache failure: tiles keep their own pending
    state (shimmer, then the tile's own timeout), and the section never
    discovers the DNA on the cache's behalf (readers never write)."""
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    assert all(t.is_loading() for t in sec.tiles())
    assert store.current_dna("ttr", "Hiro") is None
    assert store.candidate_dna("ttr", "Hiro") is None
    assert pf.pending_count + pf.in_flight_count == 0


def test_pose_section_selects_current_pose_into_the_framing_view(render_cache, qapp):
    """The framing preview shows the currently selected pose from the cache,
    at construction and when the user picks another tile."""
    from tests._render_fixtures import complete_set
    from utils.widgets.toon_customization_sections import _PoseSection
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    sec = _PoseSection("ttr", "Hiro", "dna1", "portrait")
    assert sec._adjust_view._preview.pixmap() is not None
    by_pose = {t.pose: t for t in sec.tiles()}
    sec._on_tile_clicked("waving")
    assert sec._adjust_view._preview.pixmap() is by_pose["waving"]._pixmap


def test_pose_adjust_preview_initial_state(qapp):
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    assert w.transform() == (1.0, 0.0, 0.0, 0.0)
    assert w.pixmap() is None


def test_pose_adjust_preview_set_pixmap(qapp):
    from PySide6.QtGui import QPixmap
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    pm = QPixmap(64, 64)
    pm.fill()
    w.set_pixmap(pm)
    assert w.pixmap() is pm


def test_pose_adjust_preview_set_transform(qapp):
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    w.set_transform(1.5, 0.2, -0.1, 45.0)
    assert w.transform() == (1.5, 0.2, -0.1, 45.0)


def test_pose_adjust_preview_drag_updates_offset_and_emits(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    w.resize(140, 140)
    spy = QSignalSpy(w.transform_changed)

    press = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(70, 70),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.MouseMove, QPointF(84, 70),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.MouseButtonRelease, QPointF(84, 70),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    w.mousePressEvent(press)
    w.mouseMoveEvent(move)
    w.mouseReleaseEvent(release)

    z, ox, oy, r = w.transform()
    # 14 px drag in a 140 px preview = 0.1 fraction.
    assert abs(ox - 0.1) < 1e-6
    assert abs(oy - 0.0) < 1e-6
    assert spy.count() >= 1


def test_pose_adjust_preview_wheel_changes_zoom(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    w.resize(180, 180)
    spy = QSignalSpy(w.transform_changed)

    # One wheel-up tick = +0.05 zoom.
    event = QWheelEvent(
        QPointF(90, 90), QPointF(90, 90),
        QPoint(0, 0), QPoint(0, 120),  # angleDelta y=120 (one notch up)
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    w.wheelEvent(event)

    z, ox, oy, r = w.transform()
    assert abs(z - 1.05) < 1e-6
    assert spy.count() == 1


def test_pose_adjust_view_initial_transform(qapp):
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    assert v.transform() == (1.0, 0.0, 0.0, 0.0)


def test_pose_adjust_view_zoom_slider_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    spy = QSignalSpy(v.transform_changed)
    v.set_zoom(1.5)
    assert v.transform()[0] == 1.5
    assert spy.count() >= 1


def test_pose_adjust_view_rotate_slider_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    spy = QSignalSpy(v.transform_changed)
    v.set_rotate(30.0)
    assert v.transform()[3] == 30.0
    assert spy.count() >= 1


def test_pose_adjust_view_nudge_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    spy = QSignalSpy(v.transform_changed)
    v.nudge_right()
    z, ox, oy, r = v.transform()
    # One nudge = 1 / 180 ≈ 0.00556.
    assert abs(ox - (1.0 / 180.0)) < 1e-6
    assert spy.count() == 1


def test_pose_adjust_view_has_no_back_button(qapp):
    """Back button is removed in the one-pane layout: framing is always inline."""
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    assert not hasattr(v, "back_requested")
    assert not hasattr(v, "_back_btn")


def test_pose_adjust_view_reset_restores_defaults_and_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.5, 0.3, -0.2, 45.0), saved_store=SavedColorsStore(None))
    spy = QSignalSpy(v.transform_changed)
    v.click_reset()
    assert v.transform() == (1.0, 0.0, 0.0, 0.0)
    assert spy.count() >= 1


def test_pose_section_framing_always_accessible(qapp):
    """In the one-pane layout, framing controls are always inline; no
    Adjust button needed to reveal them."""
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test")
    sec = panel.section("Toon")
    assert sec.adjust_view() is not None


def test_pose_section_expander_toggles(qapp):
    """Expand reveals the secondary tile grid; collapse hides it again."""
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test")
    sec = panel.section("Toon")
    assert not sec.is_expanded()
    sec.toggle_expand()
    assert sec.is_expanded()
    sec.toggle_expand()
    assert not sec.is_expanded()


def test_pose_section_primary_tiles_count(qapp):
    """Primary row always holds exactly 5 tiles."""
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test")
    sec = panel.section("Toon")
    assert len(sec.primary_tiles()) == 5


def test_pose_section_adjust_writes_transform_to_draft(qapp):
    """Framing controls are inline; zoom change writes through to the draft."""
    panel, mgr, overlay, _parent = _build(qapp, game="ttr", dna="dna-test")
    sec = panel.section("Toon")
    sec.adjust_view().set_zoom(1.5)
    assert panel.draft().get("portrait", {}).get("transform", {}).get("zoom") == 1.5
    overlay.close_and_save()
    saved = mgr.get("ttr", "Flossbud")
    assert saved["portrait"]["transform"]["zoom"] == 1.5


def test_pose_section_reset_removes_transform_from_draft(qapp):
    """Reset on the inline framing view clears the transform from the draft."""
    panel, _, _, _parent = _build(
        qapp, game="ttr", dna="dna-test",
        existing={"portrait": {"transform": {"zoom": 1.5, "offset_x": 0.2}}},
    )
    sec = panel.section("Toon")
    sec.adjust_view().click_reset()
    # Reset writes defaults; defaults are NOT stored (kept entry minimal).
    portrait = panel.draft().get("portrait", {})
    assert "transform" not in portrait


def test_pose_section_no_framing_without_dna(qapp):
    """Placeholder mode: no tiles, no inline framing controls."""
    panel, _, _, _parent = _build(qapp, game="ttr")  # dna=None
    sec = panel.section("Toon")
    assert sec.adjust_view() is None
    assert sec.has_placeholder()


def test_chip_row_emits_value_changed_on_click(qapp):
    from utils.widgets.toon_customization_sections import _ChipRow
    from PySide6.QtTest import QSignalSpy
    row = _ChipRow([("thin", "Thin"), ("medium", "Medium"), ("thick", "Thick")], current="medium")
    spy = QSignalSpy(row.value_changed)
    row.click_chip("thick")
    assert spy.count() == 1
    assert spy.at(0)[0] == "thick"
    assert row.current() == "thick"


def test_chip_row_visually_disabled_when_set_enabled_visual_false(qapp):
    """When the paired color is Default, the chips render greyed out
    and ignore clicks but retain the last selection."""
    from utils.widgets.toon_customization_sections import _ChipRow
    from PySide6.QtTest import QSignalSpy
    row = _ChipRow([("thin", "Thin"), ("medium", "Medium")], current="thin")
    row.set_enabled_visual(False)
    spy = QSignalSpy(row.value_changed)
    row.click_chip("medium")
    # No signal, no state change while disabled.
    assert spy.count() == 0
    assert row.current() == "thin"
    # Re-enable and click works again.
    row.set_enabled_visual(True)
    row.click_chip("medium")
    assert spy.count() == 1
    assert row.current() == "medium"


def test_chip_row_set_current_does_not_emit(qapp):
    """Programmatic set_current is a silent state mutation - never emits
    value_changed. Mirrors _SwatchRow.set_current semantics."""
    from utils.widgets.toon_customization_sections import _ChipRow
    from PySide6.QtTest import QSignalSpy
    row = _ChipRow([("thin", "Thin"), ("thick", "Thick")], current="thin")
    spy = QSignalSpy(row.value_changed)
    row.set_current("thick")
    assert spy.count() == 0
    assert row.current() == "thick"


def test_portrait_section_no_longer_exposes_circle_outline_api(qapp):
    """circle_outline_changed Signal and set_circle_outline are removed;
    fill + pattern signals must still be present."""
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PortraitSection
    sec = _PortraitSection({}, saved_store=SavedColorsStore(None))
    assert not hasattr(sec, "circle_outline_changed")
    assert not hasattr(sec, "set_circle_outline")
    assert not hasattr(sec, "current_circle_outline")
    # Fill and pattern signals remain.
    assert hasattr(sec, "color_changed")
    assert hasattr(sec, "gradient_changed")
    assert hasattr(sec, "pattern_changed")


def test_pose_section_emits_silhouette_outline_changed(qapp):
    from utils.widgets.toon_customization_sections import _PoseSection
    from PySide6.QtTest import QSignalSpy
    sec = _PoseSection("ttr", "Flossbud", dna="dna-test", current_pose="portrait")
    spy = QSignalSpy(sec.silhouette_outline_changed)
    sec.set_silhouette_outline("#ffd84a", "thick")
    assert spy.count() == 1
    args = spy.at(0)
    assert args[0] == "#ffd84a"
    assert args[1] == "thick"


def test_panel_silhouette_outline_writes_to_draft(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123")
    panel.set_silhouette_outline("#ffd84a", "medium")
    draft = panel.draft()
    assert draft["portrait"]["silhouette"]["outline"] == {
        "color": "#ffd84a", "width": "medium",
    }


def test_panel_silhouette_outline_default_color_removes_subobject(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {"outline": {"color": "#fff", "width": "thin"}}},
    })
    panel.set_silhouette_outline(None, None)
    portrait = panel.draft().get("portrait") or {}
    silhouette = portrait.get("silhouette") or {}
    assert "outline" not in silhouette


def test_panel_silhouette_shadow_writes_to_draft(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123")
    panel.set_silhouette_shadow("#000000", "strong")
    draft = panel.draft()
    assert draft["portrait"]["silhouette"]["shadow"] == {
        "color": "#000000", "softness": "strong",
    }


def test_panel_silhouette_shadow_default_color_removes_subobject(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {"shadow": {"color": "#000", "softness": "medium"}}},
    })
    panel.set_silhouette_shadow(None, None)
    sil = (panel.draft().get("portrait") or {}).get("silhouette") or {}
    assert "shadow" not in sil


def test_panel_silhouette_shadow_and_outline_coexist(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123")
    panel.set_silhouette_outline("#ffd84a", "thin")
    panel.set_silhouette_shadow("#000000", "subtle")
    sil = panel.draft()["portrait"]["silhouette"]
    assert sil["outline"] == {"color": "#ffd84a", "width": "thin"}
    assert sil["shadow"] == {"color": "#000000", "softness": "subtle"}


def test_panel_removing_shadow_preserves_existing_outline(qapp, monkeypatch, tmp_path):
    """Asymmetric removal: when silhouette has both outline and shadow,
    clearing shadow must leave outline in place. Guards the prune-empty
    cleanup in _on_silhouette_shadow."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {
            "outline": {"color": "#ffd84a", "width": "medium"},
            "shadow":  {"color": "#000000", "softness": "medium"},
        }},
    })
    panel.set_silhouette_shadow(None, None)
    sil = panel.draft()["portrait"]["silhouette"]
    assert "shadow" not in sil
    assert sil["outline"] == {"color": "#ffd84a", "width": "medium"}


def test_adjust_view_reset_clears_silhouette_alongside_transform(qapp, monkeypatch, tmp_path):
    """The inline framing Reset button must wipe both the transform AND
    the silhouette outline/shadow under portrait."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {
            "transform": {"zoom": 1.5, "offset_x": 0.1, "offset_y": 0.0, "rotate": 30.0},
            "silhouette": {
                "outline": {"color": "#fff", "width": "medium"},
                "shadow":  {"color": "#000", "softness": "medium"},
            },
        },
    })
    sec = panel.section("Toon")
    # Inline framing view is always built when DNA is set.
    sec._adjust_view.click_reset()
    portrait = panel.draft().get("portrait") or {}
    assert "transform" not in portrait
    assert "silhouette" not in portrait


def test_reset_all_resets_framing_sliders_to_neutral(qapp, monkeypatch, tmp_path):
    """reset_all must reset the zoom/rotate sliders to the default neutral
    position (zoom=1.0, rotate=0). Without this, the sliders keep their
    prior values and the next nudge re-applies a stale transform."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    panel, _, _, _parent = _build(
        qapp,
        game="ttr",
        dna="dna-test-sliders",
        existing={
            "portrait": {
                "transform": {"zoom": 2.0, "offset_x": 0.3, "offset_y": 0.0, "rotate": 45.0}
            }
        },
    )
    sec = panel.section("Toon")
    adjust = sec._adjust_view
    # Confirm the sliders loaded the saved values.
    assert adjust._zoom_slider.value() == 200
    assert adjust._rot_slider.value() == 45

    panel.reset_all()

    # After reset the zoom slider must be back at 100 (== 1.0x).
    assert adjust._zoom_slider.value() == 100
    # Rotate slider must be back at 0.
    assert adjust._rot_slider.value() == 0


def test_set_transform_from_draft_syncs_sliders(qapp):
    """set_transform_from_draft must sync the zoom slider, rotate slider, and
    their value labels in addition to the preview. Regression: the view is
    built eagerly with defaults (1.0, 0, 0, 0), then set_transform_from_draft
    is called after construction. Before the fix, the sliders stayed at their
    default positions while the preview showed the correct saved frame; the
    first slider nudge then snapped the preview back to the stale slider value."""
    from utils.widgets.toon_customization_sections import _PoseSection

    sec = _PoseSection("ttr", "Flossbud", dna="dna-test-slider-sync", current_pose="portrait")
    # The _PoseAdjustView is always built when a DNA is set.
    assert sec._adjust_view is not None

    # Seed a non-default framing transform after construction, exactly as the
    # overlay does (customization_overlay.py line 325).
    sec.set_transform_from_draft((1.5, 0.1, -0.05, 30.0))

    adjust = sec._adjust_view

    # Preview must reflect the saved transform.
    z, ox, oy, r = adjust._preview.transform()
    assert abs(z - 1.5) < 1e-6
    assert abs(r - 30.0) < 1e-6

    # Zoom slider: range 50-300, value = zoom * 100.
    assert adjust._zoom_slider.value() == 150
    assert adjust._zoom_value.text() == "1.50x"

    # Rotate slider: range -180..180, value = int(rot).
    assert adjust._rot_slider.value() == 30
    assert adjust._rot_value.text() == "30°"
