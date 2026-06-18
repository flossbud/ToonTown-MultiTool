"""Smoke test: section widgets are importable from the extracted module."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_section_module_exports_widgets(qapp):
    from utils.widgets.toon_customization_sections import (
        PRESET_SWATCHES,
        PRIMARY_POSES,
        _SwatchRow,
        _SimpleColorSection,
        _CardSection,
        _ChipRow,
        _PoseTile,
        _PoseAdjustPreview,
        _PoseAdjustView,
        _PoseSection,
        _PortraitSection,
    )
    assert isinstance(PRESET_SWATCHES, tuple)
    assert len(PRIMARY_POSES) == 5
    assert _SwatchRow is not None
    assert _SimpleColorSection is not None
    assert _CardSection is not None
    assert _ChipRow is not None
    assert _PoseTile is not None
    assert _PoseAdjustPreview is not None
    assert _PoseAdjustView is not None
    assert _PoseSection is not None
    assert _PortraitSection is not None


def test_card_section_body_toggle(qapp):
    from utils.widgets.toon_customization_sections import _CardSection
    sec = _CardSection("#4a7cff", None)  # body off by default
    got = []
    sec.body_changed.connect(got.append)
    # Toggle ON -> body well un-hidden; no emit yet.
    sec._body_toggle.setChecked(True)
    assert not sec._body_row.isHidden()
    assert len(got) == 0
    # Pick a body color -> body_changed(hex).
    sec._body_row._apply_committed("#aa3377")
    assert got[-1] == "#aa3377"
    # Toggle OFF -> body_changed(None).
    sec._body_toggle.setChecked(False)
    assert got[-1] is None


def test_card_section_existing_body_starts_on(qapp):
    from utils.widgets.toon_customization_sections import _CardSection
    sec = _CardSection("#4a7cff", "#aa3377")
    assert sec._body_toggle.isChecked()
    assert not sec._body_row.isHidden()
    assert sec._body_row.current() == "#aa3377"


def test_pose_tile_pinned_dimensions(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    assert _PoseTile._TILE_W == 160
    assert _PoseTile._TILE_H == 110
    assert _PoseTile._BOX == 100


def test_pose_tile_tooltip_matches_pose(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    tile = _PoseTile("portrait-delighted")
    assert tile.toolTip() == "portrait-delighted"


def test_pose_tile_no_label_pixels_below_box(qapp):
    """The label area (rows below _BOX) must be free of any rendered
    text pixels. Render the tile to an image and assert the bottom
    band is uniformly the tile background (no non-background pixels).

    Tile draws on its parent surface, so we render via QPainter onto
    a transparent QImage we own."""
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QWidget
    from utils.widgets.toon_customization_sections import _PoseTile

    tile = _PoseTile("portrait")
    tile.resize(_PoseTile._TILE_W, _PoseTile._TILE_H)
    image = QImage(
        QSize(_PoseTile._TILE_W, _PoseTile._TILE_H),
        QImage.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.transparent)
    painter = QPainter(image)
    tile.render(painter, QPoint(0, 0), renderFlags=QWidget.RenderFlag.DrawChildren)
    painter.end()

    # Sample the label band (below _BOX). For each pixel: must be
    # transparent (no paint touched it).
    label_y_start = _PoseTile._BOX + 2
    for y in range(label_y_start, _PoseTile._TILE_H):
        for x in range(_PoseTile._TILE_W):
            px = image.pixelColor(x, y)
            assert px.alpha() == 0, (
                f"label band has non-transparent pixel at ({x},{y}): "
                f"rgba={px.red()},{px.green()},{px.blue()},{px.alpha()}"
            )


def test_pose_section_expanded_grid_uses_3_columns(qapp):
    """The expanded grid (secondary poses) uses columns 0, 1, 2 only."""
    from utils.widgets.toon_customization_sections import _PoseSection, PRIMARY_POSES

    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()

    # The expanded widget's VBoxLayout contains a QGridLayout.
    assert section._expanded_widget is not None, "expanded widget must exist"
    exp_layout = section._expanded_widget.layout()
    grid = None
    for i in range(exp_layout.count()):
        item = exp_layout.itemAt(i)
        if item.layout() is not None and hasattr(item.layout(), "getItemPosition"):
            grid = item.layout()
            break
    assert grid is not None, "could not find QGridLayout inside expanded widget"

    # Secondary tiles are those not in the primary row.
    secondary_tiles = [t for t in section._tiles if t not in section._primary_tile_list]
    columns_seen = set()
    for tile in secondary_tiles:
        idx_in_grid = grid.indexOf(tile)
        assert idx_in_grid != -1, f"tile {tile.pose} not found in expanded grid"
        _row, col, _rs, _cs = grid.getItemPosition(idx_in_grid)
        columns_seen.add(col)
    assert columns_seen == {0, 1, 2}, (
        f"expected only columns 0,1,2 in expanded grid; got {sorted(columns_seen)}"
    )


def test_pose_section_expanded_grid_width_fits_compact_viewport(qapp):
    """The expanded pose grid's minimum width must be <= 527 (the compact-mode
    panel section viewport width after the vertical scrollbar). The 3-column
    grid of 160 px tiles fits at ~508 px; this guards against regressions."""
    from utils.widgets.toon_customization_sections import _PoseSection

    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()
    assert section._expanded_widget is not None
    section._expanded_widget.layout().activate()
    hint = section._expanded_widget.minimumSizeHint().width()
    assert hint <= 527, (
        f"expanded grid min width {hint} exceeds compact viewport (527 px); "
        f"horizontal scroll will appear"
    )


def test_pose_adjust_preview_size_140(qapp):
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    assert _PoseAdjustPreview._SIZE == 140


def test_pose_adjust_view_min_width_fits_compact(qapp):
    """Framing view's minimum width must be <= 527 so the inline
    framing controls don't inflate the section past the compact panel
    viewport width."""
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    view = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    view.layout().activate()
    hint = view.minimumSizeHint().width()
    assert hint <= 527, (
        f"adjust view min width {hint} exceeds compact viewport "
        f"(527 px); will force horizontal scroll on the parent stack"
    )


def test_pose_section_inline_framing_width_fits_compact(qapp):
    """Regression guard: the inline framing view (always built when DNA is
    set) must not exceed 527 px so the section doesn't force horizontal
    scroll in the compact panel viewport."""
    from utils.widgets.toon_customization_sections import _PoseSection
    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()
    # Inline framing view is built unconditionally during _build().
    assert section._adjust_view is not None, "inline framing view must be built"
    section._adjust_view.layout().activate()
    hint = section._adjust_view.minimumSizeHint().width()
    assert hint <= 527, (
        f"inline framing view min width {hint} exceeds compact "
        f"viewport (527 px); horizontal scroll will appear"
    )


def test_pose_adjust_view_attributes_preserved(qapp):
    """The one-pane rewrite must keep every widget attribute name + signal
    that consumers depend on. The Back button is intentionally absent
    (no page to navigate back to)."""
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    view = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    assert view._preview is not None
    assert view._left_btn is not None
    assert view._up_btn is not None
    assert view._down_btn is not None
    assert view._right_btn is not None
    assert view._zoom_slider is not None
    assert view._zoom_value is not None
    assert view._rot_slider is not None
    assert view._rot_value is not None
    assert view._sil_outline_color_row is not None
    assert view._sil_outline_chip is not None
    assert view._sil_shadow_color_row is not None
    assert view._sil_shadow_chip is not None
    assert view._reset_btn is not None
    # Back button removed in one-pane layout.
    assert not hasattr(view, "_back_btn")


def test_pose_primary_five_and_expand(qapp):
    """Primary row has exactly 5 tiles; expand reveals all 13."""
    from utils.rendition_poses import POSE_NAMES
    from utils.widgets.toon_customization_sections import _PoseSection, PRIMARY_POSES

    assert len(PRIMARY_POSES) == 5
    s = _PoseSection("dna-test", PRIMARY_POSES[0])
    qapp.processEvents()

    assert len(s.primary_tiles()) == 5
    assert not s.is_expanded()

    s.toggle_expand()
    assert s.is_expanded()
    assert s._expanded_widget is not None
    # isHidden() checks the explicit flag (not parent-chain visibility).
    assert not s._expanded_widget.isHidden()

    s.toggle_expand()
    assert not s.is_expanded()
    assert s._expanded_widget.isHidden()

    assert len(s.tiles()) == len(POSE_NAMES)

