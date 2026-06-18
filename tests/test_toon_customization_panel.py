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


def test_cc_has_icon_section(qapp):
    panel, _, _, _parent = _build(qapp, game="cc")
    assert "Icon" in panel.section_names()


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
    _reset_singletons()
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


def test_refresh_button_calls_invalidate_dna(qapp, monkeypatch):
    """Clicking the section refresh button must invalidate cached
    pixmaps for the current DNA."""
    from utils.rendition_poses import RenditionPoseFetcher
    calls = []
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "invalidate_dna",
        lambda self, dna: calls.append(dna),
    )
    # Also stub `request` so we don't actually fetch.
    monkeypatch.setattr(
        RenditionPoseFetcher, "request", lambda self, dna, pose: None,
    )
    panel, _, _, _parent = _build(qapp, game="ttr", dna="dna-test-123")
    sec = panel.section("Toon")
    sec.click_refresh()
    assert "dna-test-123" in calls


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


def _reset_singletons():
    """Reset module-level singletons for clean test fixtures."""
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None


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
    sec = _PoseSection(dna="dna-test", current_pose="portrait")
    spy = QSignalSpy(sec.silhouette_outline_changed)
    sec.set_silhouette_outline("#ffd84a", "thick")
    assert spy.count() == 1
    args = spy.at(0)
    assert args[0] == "#ffd84a"
    assert args[1] == "thick"


def test_panel_silhouette_outline_writes_to_draft(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    _reset_singletons()
    panel, _, _, _parent = _build(qapp, dna="dna-test-123")
    panel.set_silhouette_outline("#ffd84a", "medium")
    draft = panel.draft()
    assert draft["portrait"]["silhouette"]["outline"] == {
        "color": "#ffd84a", "width": "medium",
    }


def test_panel_silhouette_outline_default_color_removes_subobject(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    _reset_singletons()
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {"outline": {"color": "#fff", "width": "thin"}}},
    })
    panel.set_silhouette_outline(None, None)
    portrait = panel.draft().get("portrait") or {}
    silhouette = portrait.get("silhouette") or {}
    assert "outline" not in silhouette


def test_panel_silhouette_shadow_writes_to_draft(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    _reset_singletons()
    panel, _, _, _parent = _build(qapp, dna="dna-test-123")
    panel.set_silhouette_shadow("#000000", "strong")
    draft = panel.draft()
    assert draft["portrait"]["silhouette"]["shadow"] == {
        "color": "#000000", "softness": "strong",
    }


def test_panel_silhouette_shadow_default_color_removes_subobject(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    _reset_singletons()
    panel, _, _, _parent = _build(qapp, dna="dna-test-123", existing={
        "portrait": {"silhouette": {"shadow": {"color": "#000", "softness": "medium"}}},
    })
    panel.set_silhouette_shadow(None, None)
    sil = (panel.draft().get("portrait") or {}).get("silhouette") or {}
    assert "shadow" not in sil


def test_panel_silhouette_shadow_and_outline_coexist(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    _reset_singletons()
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
    _reset_singletons()
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
    _reset_singletons()
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
