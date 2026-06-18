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
        _SwatchRow,
        _SimpleColorSection,
        _ChipRow,
        _PoseTile,
        _PoseAdjustPreview,
        _PoseAdjustView,
        _PoseSection,
        _PortraitSection,
    )
    assert isinstance(PRESET_SWATCHES, tuple)
    assert _SwatchRow is not None
    assert _SimpleColorSection is not None
    assert _ChipRow is not None
    assert _PoseTile is not None
    assert _PoseAdjustPreview is not None
    assert _PoseAdjustView is not None
    assert _PoseSection is not None
    assert _PortraitSection is not None


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


def test_pose_section_3_columns(qapp):
    """Every tile lives in column 0, 1, or 2 — no column 3."""
    from utils.widgets.toon_customization_sections import _PoseSection

    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()
    grid_page = section._grid_page
    layout = grid_page.layout()
    grid_idx = None
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.layout() is not None and hasattr(item.layout(), "getItemPosition"):
            grid_idx = i
            break
    assert grid_idx is not None, "could not find QGridLayout inside grid page"
    grid = layout.itemAt(grid_idx).layout()
    columns_seen = set()
    for tile in section._tiles:
        idx_in_grid = grid.indexOf(tile)
        assert idx_in_grid != -1, f"tile {tile.pose} not found in grid"
        row, col, _rs, _cs = grid.getItemPosition(idx_in_grid)
        columns_seen.add(col)
    assert columns_seen == {0, 1, 2}, (
        f"expected only columns 0,1,2; got {sorted(columns_seen)}"
    )


def test_pose_section_grid_width_fits_compact_viewport(qapp):
    """Grid page's minimum width must be <= 527 (the compact-mode
    panel section viewport width after the vertical scrollbar)."""
    from utils.widgets.toon_customization_sections import _PoseSection

    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()
    section._grid_page.layout().activate()
    hint = section._grid_page.minimumSizeHint().width()
    assert hint <= 527, (
        f"grid page min width {hint} exceeds compact viewport (527 px); "
        f"horizontal scroll will appear"
    )


def test_pose_adjust_preview_size_140(qapp):
    from utils.widgets.toon_customization_sections import _PoseAdjustPreview
    assert _PoseAdjustPreview._SIZE == 140


def test_pose_adjust_view_min_width_fits_compact(qapp):
    """Adjust view's minimum width must be <= 527 so the
    QStackedWidget (grid + adjust) doesn't inflate past the
    compact panel viewport."""
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.toon_customization_sections import _PoseAdjustView
    view = _PoseAdjustView(initial=(1.0, 0.0, 0.0, 0.0), saved_store=SavedColorsStore(None))
    view.layout().activate()
    hint = view.minimumSizeHint().width()
    assert hint <= 527, (
        f"adjust view min width {hint} exceeds compact viewport "
        f"(527 px); will force horizontal scroll on the parent stack"
    )


def test_pose_section_stack_min_width_fits_compact(qapp):
    """Regression guard for the original bug: the QStackedWidget
    that hosts the grid + adjust subview must not exceed 527 px
    after the adjust view is constructed."""
    from utils.widgets.toon_customization_sections import _PoseSection
    section = _PoseSection(dna="dna-abc-123", current_pose="portrait")
    qapp.processEvents()
    # Force the adjust view to exist (same trigger as the production
    # path: _Panel.populate calls set_silhouette_outline which
    # lazy-builds the adjust view).
    section._ensure_adjust_view()
    qapp.processEvents()
    section._stack.layout().activate() if section._stack.layout() else None
    hint = section._stack.minimumSizeHint().width()
    assert hint <= 527, (
        f"pose-section stack min width {hint} exceeds compact "
        f"viewport (527 px); horizontal scroll will appear"
    )


def test_pose_adjust_view_attributes_preserved(qapp):
    """The vertical-stack rewrite must keep every widget attribute
    name + signal that consumers depend on."""
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
    assert view._back_btn is not None
    assert view._reset_btn is not None

