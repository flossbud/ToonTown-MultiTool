"""Reusable grid of CC race tiles. Extracted from RacePickerDialog so
the new ToonCustomizationDialog can embed it as a section.

Each tile shows a pre-tinted CC badge (skin color + asset). Click to
select. Emits `selection_changed(stem)` when the user picks a tile.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QVBoxLayout, QWidget

from utils import cc_race_assets
from utils.cc_badge_paint import paint_cc_badge


_TILE_PX = 80
_GRID_COLS = 5


class _RaceTile(QFrame):
    """One race tile. Shows a tinted badge + label. Click to select."""

    clicked_stem = Signal(str)

    def __init__(self, stem: str, skin: QColor, parent=None):
        super().__init__(parent)
        self._stem = stem
        self._skin = skin
        self._selected = False
        self._auto = False
        self.setFixedSize(QSize(_TILE_PX + 8, _TILE_PX + 28))
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)

    @property
    def stem(self) -> str:
        return self._stem

    def set_selected(self, on: bool) -> None:
        if self._selected != on:
            self._selected = on
            self.update()

    def set_auto(self, on: bool) -> None:
        if self._auto != on:
            self._auto = on
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._selected:
            p.fillRect(self.rect(), QColor(74, 124, 255, 60))
        badge_rect = QRect(4, 4, _TILE_PX, _TILE_PX)
        paint_cc_badge(p, badge_rect, self._skin, self._stem, slot_number=1)
        p.setPen(QColor(220, 220, 230))
        p.drawText(
            QRect(0, _TILE_PX + 6, self.width(), 18),
            Qt.AlignCenter,
            self._stem,
        )
        if self._auto:
            p.setBrush(QColor(60, 70, 90))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRect(self.width() - 32, 6, 26, 12), 4, 4)
            p.setPen(QColor(220, 220, 230))
            p.drawText(
                QRect(self.width() - 32, 6, 26, 12),
                Qt.AlignCenter,
                "auto",
            )
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked_stem.emit(self._stem)
        super().mousePressEvent(event)


class RaceIconGridWidget(QWidget):
    """Scrollable grid of CC race tiles. Emits selection_changed(stem)."""

    selection_changed = Signal(str)

    def __init__(
        self,
        skin_color: QColor,
        selected_stem: Optional[str],
        auto_stem: Optional[str],
        parent=None,
    ):
        super().__init__(parent)
        self._skin = skin_color
        self._auto = auto_stem
        self._selected: Optional[str] = selected_stem or auto_stem
        self._tiles: list[_RaceTile] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(8)
        for i, stem in enumerate(sorted(self._list_asset_stems())):
            tile = _RaceTile(stem, self._skin, parent=host)
            tile.set_selected(stem == self._selected)
            tile.set_auto(stem == self._auto)
            tile.clicked_stem.connect(self.select_stem)
            grid.addWidget(tile, i // _GRID_COLS, i % _GRID_COLS)
            self._tiles.append(tile)
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _list_asset_stems(self) -> list[str]:
        d = cc_race_assets._asset_dir()
        if not os.path.isdir(d):
            return []
        return [
            os.path.splitext(name)[0]
            for name in os.listdir(d)
            if name.lower().endswith(".png")
        ]

    # -- Public API ------------------------------------------------------------

    def tiles(self) -> list[_RaceTile]:
        return list(self._tiles)

    def selected_stem(self) -> Optional[str]:
        return self._selected

    def auto_marked_stem(self) -> Optional[str]:
        return self._auto

    def select_stem(self, stem: str) -> None:
        if stem not in (t.stem for t in self._tiles):
            return
        if self._selected == stem:
            return
        self._selected = stem
        for t in self._tiles:
            t.set_selected(t.stem == stem)
        self.selection_changed.emit(stem)
