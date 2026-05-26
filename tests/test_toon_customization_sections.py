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

