"""Tests for ToonCustomizationDialog (sidebar/preview/save flow)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeManager:
    """In-memory stand-in for ToonCustomizationsManager."""

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
    from utils.widgets.toon_customization_dialog import ToonCustomizationDialog
    from PySide6.QtGui import QColor
    mgr = manager or _FakeManager()
    if existing:
        mgr.set(game, "Flossbud", existing)
    dlg = ToonCustomizationDialog(
        game=game, toon_name="Flossbud", manager=mgr,
        skin_color=QColor("#d9a04e") if game == "cc" else None,
        auto_stem="dog" if game == "cc" else None,
        dna=dna,
    )
    return dlg, mgr


def test_dialog_constructs(qapp):
    dlg, _ = _build(qapp)
    assert dlg.windowTitle().endswith("Flossbud")


def test_ttr_has_no_icon_section(qapp):
    dlg, _ = _build(qapp, game="ttr")
    assert "Icon" not in dlg.section_names()


def test_cc_has_icon_section(qapp):
    dlg, _ = _build(qapp, game="cc")
    assert "Icon" in dlg.section_names()


def test_save_writes_draft_to_manager(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_accent("#56c856")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#56c856"}


def test_cancel_does_not_touch_manager(qapp):
    dlg, mgr = _build(qapp, existing={"accent": "#abcdef"})
    dlg.set_accent("#56c856")
    dlg.reject()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#abcdef"}


def test_reset_all_empties_draft(qapp):
    dlg, _ = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    dlg.reset_all()
    assert dlg.draft() == {}


def test_draft_loaded_from_existing(qapp):
    dlg, _ = _build(qapp, existing={"accent": "#56c856"})
    assert dlg.draft() == {"accent": "#56c856"}


def test_set_body(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_body("#101020")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}


def test_set_accent_to_none_removes_field(qapp):
    dlg, mgr = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    dlg.set_accent(None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}


def test_set_portrait_color(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_color("#d9a04e")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#d9a04e"}}


def test_set_portrait_color_to_none_removes_color(qapp):
    dlg, mgr = _build(qapp, existing={"portrait": {"color": "#d9a04e"}})
    dlg.set_portrait_color(None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_set_gradient(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_gradient({"start": "#ff0000", "end": "#00ff00"})
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"gradient": {"start": "#ff0000", "end": "#00ff00"}}
    }


def test_set_pattern(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_pattern("dots", "#ffffff")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"pattern": {"name": "dots", "color": "#ffffff"}}
    }


def test_clear_pattern(qapp):
    dlg, mgr = _build(qapp, existing={
        "portrait": {"pattern": {"name": "dots", "color": "#fff000"}}
    })
    dlg.set_portrait_pattern(None, None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_portrait_combines_color_pattern(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_color("#d9a04e")
    dlg.set_portrait_pattern("stripes_diag", "#101020")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {
            "color": "#d9a04e",
            "pattern": {"name": "stripes_diag", "color": "#101020"},
        }
    }


def test_cc_icon_section_initial_selection(qapp):
    """When CC entry has icon_stem, the Icon section reflects it."""
    dlg, _ = _build(
        qapp, game="cc",
        existing={"icon_stem": "dog"},
    )
    sec = dlg.section("Icon")
    assert sec.selected_stem() == "dog"


def test_cc_icon_section_save(qapp):
    dlg, mgr = _build(qapp, game="cc")
    dlg.set_icon_stem("dog")
    dlg.accept_save()
    assert mgr.get("cc", "Flossbud") == {"icon_stem": "dog"}


def test_cc_icon_set_to_none_removes_field(qapp):
    dlg, mgr = _build(qapp, game="cc", existing={"icon_stem": "dog"})
    dlg.set_icon_stem(None)
    dlg.accept_save()
    assert mgr.get("cc", "Flossbud") == {}


def test_pose_tile_initial_state(qapp):
    from utils.widgets.toon_customization_dialog import _PoseTile
    tile = _PoseTile("portrait-grin")
    assert tile.pose == "portrait-grin"
    assert tile.is_selected() is False
    assert tile.has_pixmap() is False


def test_pose_tile_set_pixmap(qapp):
    from PySide6.QtGui import QPixmap
    from utils.widgets.toon_customization_dialog import _PoseTile
    pm = QPixmap(32, 32)
    pm.fill()
    tile = _PoseTile("waving")
    tile.set_pixmap(pm)
    assert tile.has_pixmap() is True


def test_pose_tile_set_selected_toggles(qapp):
    from utils.widgets.toon_customization_dialog import _PoseTile
    tile = _PoseTile("head")
    tile.set_selected(True)
    assert tile.is_selected() is True
    tile.set_selected(False)
    assert tile.is_selected() is False


def test_pose_tile_click_emits_pose(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseTile
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


def test_ttr_dialog_has_toon_section_first(qapp):
    dlg, _ = _build(qapp, game="ttr")
    names = dlg.section_names()
    assert names[0] == "Toon"
    # Order: Toon, Portrait, Accent, Body
    assert names == ["Toon", "Portrait", "Accent", "Body"]


def test_cc_dialog_has_no_toon_section(qapp):
    dlg, _ = _build(qapp, game="cc")
    assert "Toon" not in dlg.section_names()


def test_set_pose_updates_draft_and_save_persists(qapp):
    dlg, mgr = _build(qapp, dna="dna-test-123")
    dlg.set_pose("portrait-grin")
    assert dlg.draft().get("pose") == "portrait-grin"
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud").get("pose") == "portrait-grin"


def test_set_pose_to_default_removes_field(qapp):
    dlg, mgr = _build(qapp, existing={"pose": "portrait-grin"}, dna="dna-test-123")
    dlg.set_pose("portrait")  # back to default
    dlg.accept_save()
    # "portrait" is the default; it does NOT need to be stored.
    saved = mgr.get("ttr", "Flossbud")
    assert "pose" not in saved


def test_pose_section_dna_none_shows_placeholder(qapp):
    """When the slot has no DNA, the Toon section shows a placeholder
    message instead of the tile grid."""
    dlg, _ = _build(qapp, game="ttr")  # _build passes dna=None
    sec = dlg.section("Toon")
    assert sec.has_placeholder() is True
    assert sec.tiles() == []


def test_pose_section_with_dna_builds_13_tiles(qapp):
    dlg, _ = _build(qapp, game="ttr", dna="dna-test-123")
    sec = dlg.section("Toon")
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
    dlg, _ = _build(qapp, game="ttr", dna="dna-test-123")
    sec = dlg.section("Toon")
    sec.click_refresh()
    assert "dna-test-123" in calls


def test_pose_adjust_preview_initial_state(qapp):
    from utils.widgets.toon_customization_dialog import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    assert w.transform() == (1.0, 0.0, 0.0, 0.0)
    assert w.pixmap() is None


def test_pose_adjust_preview_set_pixmap(qapp):
    from PySide6.QtGui import QPixmap
    from utils.widgets.toon_customization_dialog import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    pm = QPixmap(64, 64)
    pm.fill()
    w.set_pixmap(pm)
    assert w.pixmap() is pm


def test_pose_adjust_preview_set_transform(qapp):
    from utils.widgets.toon_customization_dialog import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    w.set_transform(1.5, 0.2, -0.1, 45.0)
    assert w.transform() == (1.5, 0.2, -0.1, 45.0)


def test_pose_adjust_preview_drag_updates_offset_and_emits(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustPreview
    w = _PoseAdjustPreview()
    w.resize(180, 180)
    spy = QSignalSpy(w.transform_changed)

    press = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(90, 90),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.MouseMove, QPointF(108, 90),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.MouseButtonRelease, QPointF(108, 90),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    w.mousePressEvent(press)
    w.mouseMoveEvent(move)
    w.mouseReleaseEvent(release)

    z, ox, oy, r = w.transform()
    # 18 px drag in a 180 px preview = 0.1 fraction.
    assert abs(ox - 0.1) < 1e-6
    assert abs(oy - 0.0) < 1e-6
    assert spy.count() >= 1


def test_pose_adjust_preview_wheel_changes_zoom(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustPreview
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
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0))
    assert v.transform() == (1.0, 0.0, 0.0, 0.0)


def test_pose_adjust_view_zoom_slider_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0))
    spy = QSignalSpy(v.transform_changed)
    v.set_zoom(1.5)
    assert v.transform()[0] == 1.5
    assert spy.count() >= 1


def test_pose_adjust_view_rotate_slider_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0))
    spy = QSignalSpy(v.transform_changed)
    v.set_rotate(30.0)
    assert v.transform()[3] == 30.0
    assert spy.count() >= 1


def test_pose_adjust_view_nudge_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0))
    spy = QSignalSpy(v.transform_changed)
    v.nudge_right()
    z, ox, oy, r = v.transform()
    # One nudge = 1 / 180 ≈ 0.00556.
    assert abs(ox - (1.0 / 180.0)) < 1e-6
    assert spy.count() == 1


def test_pose_adjust_view_back_button_emits_back_requested(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0))
    spy = QSignalSpy(v.back_requested)
    v.click_back()
    assert spy.count() == 1


def test_pose_adjust_view_reset_restores_defaults_and_emits(qapp):
    from PySide6.QtTest import QSignalSpy
    from utils.widgets.toon_customization_dialog import _PoseAdjustView
    v = _PoseAdjustView(initial=(1.5, 0.3, -0.2, 45.0))
    spy = QSignalSpy(v.transform_changed)
    v.click_reset()
    assert v.transform() == (1.0, 0.0, 0.0, 0.0)
    assert spy.count() >= 1


def test_pose_section_starts_in_grid_mode(qapp):
    dlg, _ = _build(qapp, game="ttr", dna="dna-test")
    sec = dlg.section("Toon")
    assert sec.is_adjusting() is False


def test_pose_section_adjust_button_switches_mode(qapp):
    dlg, _ = _build(qapp, game="ttr", dna="dna-test")
    sec = dlg.section("Toon")
    sec.click_adjust()
    assert sec.is_adjusting() is True


def test_pose_section_back_returns_to_grid(qapp):
    dlg, _ = _build(qapp, game="ttr", dna="dna-test")
    sec = dlg.section("Toon")
    sec.click_adjust()
    assert sec.is_adjusting() is True
    sec.click_back()
    assert sec.is_adjusting() is False


def test_pose_section_adjust_writes_transform_to_draft(qapp):
    dlg, mgr = _build(qapp, game="ttr", dna="dna-test")
    sec = dlg.section("Toon")
    sec.click_adjust()
    sec.adjust_view().set_zoom(1.5)
    assert dlg.draft().get("portrait", {}).get("transform", {}).get("zoom") == 1.5
    dlg.accept_save()
    saved = mgr.get("ttr", "Flossbud")
    assert saved["portrait"]["transform"]["zoom"] == 1.5


def test_pose_section_reset_removes_transform_from_draft(qapp):
    dlg, _ = _build(
        qapp, game="ttr", dna="dna-test",
        existing={"portrait": {"transform": {"zoom": 1.5, "offset_x": 0.2}}},
    )
    sec = dlg.section("Toon")
    sec.click_adjust()
    sec.adjust_view().click_reset()
    # Reset writes defaults; defaults are NOT stored (kept entry minimal).
    portrait = dlg.draft().get("portrait", {})
    assert "transform" not in portrait


def test_pose_section_adjust_button_disabled_without_dna(qapp):
    dlg, _ = _build(qapp, game="ttr")  # dna=None
    sec = dlg.section("Toon")
    # Placeholder mode; adjust button is either hidden or disabled.
    # The contract: click_adjust() is a no-op in that mode.
    sec.click_adjust()
    assert sec.is_adjusting() is False


def test_chip_row_emits_value_changed_on_click(qapp):
    from utils.widgets.toon_customization_dialog import _ChipRow
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
    from utils.widgets.toon_customization_dialog import _ChipRow
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
