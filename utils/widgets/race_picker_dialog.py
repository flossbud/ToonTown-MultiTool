"""RacePickerDialog: lets the user pick a CC race icon manually.

Opens from the bottom-left pencil overlay on a CC badge. Grid of all
assets in `assets/ccraces/`, each pre-tinted with the toon's skin color
on the complementary bg. Save/Cancel/"Use auto-detected" actions.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from utils import cc_race_assets
from utils.cc_badge_paint import paint_cc_badge


_TILE_PX = 80    # tile width/height for the badge area
_GRID_COLS = 5


class _RaceTile(QFrame):
    """One race choice. Shows a pre-tinted badge + label, click to select."""

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
        # Background container; subtle highlight when selected.
        if self._selected:
            p.fillRect(self.rect(), QColor(74, 124, 255, 60))
        # Badge area
        badge_rect = QRect(4, 4, _TILE_PX, _TILE_PX)
        paint_cc_badge(p, badge_rect, self._skin, self._stem, slot_number=1)
        # Label
        p.setPen(QColor(220, 220, 230))
        p.drawText(
            QRect(0, _TILE_PX + 6, self.width(), 18),
            Qt.AlignCenter,
            self._stem,
        )
        # Auto marker (small badge in the corner)
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


class RacePickerDialog(QDialog):
    """Modal grid for picking the icon for a CC toon."""

    def __init__(
        self,
        toon_name: str,
        current_override_stem: Optional[str],
        auto_detected_stem: Optional[str],
        skin_color: QColor,
        parent=None,
    ):
        super().__init__(parent)
        self._toon_name = toon_name
        self._auto_stem = auto_detected_stem
        self._skin = skin_color
        # Default selection: override > auto > nothing.
        self._selected: Optional[str] = (
            current_override_stem or auto_detected_stem
        )
        self._result_action: tuple[str, Optional[str]] = ("cancel", None)
        self._tiles: list[_RaceTile] = []

        self.setWindowTitle(f"Set icon for {toon_name}")
        self.setMinimumWidth(560)
        self._build_ui()

    # -- Public test API -------------------------------------------------------

    def title_text(self) -> str:
        return self.windowTitle()

    def tiles(self) -> list[_RaceTile]:
        return list(self._tiles)

    def selected_stem(self) -> Optional[str]:
        return self._selected

    def auto_marked_stem(self) -> Optional[str]:
        return self._auto_stem

    def result_action(self) -> tuple[str, Optional[str]]:
        return self._result_action

    def select_stem(self, stem: str) -> None:
        if stem not in (t.stem for t in self._tiles):
            return
        self._selected = stem
        for t in self._tiles:
            t.set_selected(t.stem == stem)

    def accept_save(self) -> None:
        if self._selected is None:
            return
        self._result_action = ("set", self._selected)
        self.accept()

    def accept_use_auto(self) -> None:
        self._result_action = ("clear", None)
        self.accept()

    # -- UI build --------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)

        title = QLabel(f"<b>Set icon for {self._toon_name}</b>")
        outer.addWidget(title)

        sub_text = "Manual override. Applies wherever this toon's badge appears."
        if self._auto_stem:
            sub_text += f"   (auto-detected: {self._auto_stem})"
        subtitle = QLabel(sub_text)
        subtitle.setStyleSheet("color: #8a93a8; font-size: 11px;")
        outer.addWidget(subtitle)

        # Grid of tiles
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(8)

        stems = sorted(self._list_asset_stems())
        for i, stem in enumerate(stems):
            tile = _RaceTile(stem, self._skin, parent=host)
            tile.set_selected(stem == self._selected)
            tile.set_auto(stem == self._auto_stem)
            tile.clicked_stem.connect(self.select_stem)
            grid.addWidget(tile, i // _GRID_COLS, i % _GRID_COLS)
            self._tiles.append(tile)

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        # Footer
        footer = QHBoxLayout()
        use_auto = QPushButton("Use auto-detected (clears override)")
        use_auto.setFlat(True)
        use_auto.setStyleSheet("color: #8aa3d6;")
        use_auto.setEnabled(self._auto_stem is not None)
        if self._auto_stem is None:
            use_auto.setToolTip(
                "No auto-detected race for this toon yet"
            )
        use_auto.clicked.connect(self.accept_use_auto)
        self._use_auto_button = use_auto  # for testability
        footer.addWidget(use_auto)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept_save)
        footer.addWidget(save)
        outer.addLayout(footer)

    def _list_asset_stems(self) -> list[str]:
        d = cc_race_assets._asset_dir()  # internal but stable; see Task 1
        if not os.path.isdir(d):
            return []
        return [
            os.path.splitext(name)[0]
            for name in os.listdir(d)
            if name.lower().endswith(".png")
        ]
