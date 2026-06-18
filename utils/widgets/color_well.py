from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from utils.widgets.color_picker_overlay import ColorPickerOverlay

class ColorWell(QWidget):
    color_picked = Signal(object)          # hex str | None  (== _SwatchRow contract)

    def __init__(self, current: Optional[str] = None, *, saved_store, parent=None):
        super().__init__(parent)
        self._current = current
        self._store = saved_store
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        self._btn = QPushButton(); self._btn.setFixedSize(46, 30); self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._open_picker)
        lay.addWidget(self._btn); lay.addStretch(1)
        self._refresh()

    def current(self) -> Optional[str]: return self._current
    def set_current(self, hex_: Optional[str]) -> None:
        self._current = hex_; self._refresh()           # no emit

    def _refresh(self):
        c = self._current or "transparent"
        border = "#555a70" if self._current else "#4a5070"
        self._btn.setStyleSheet(f"border:1px solid {border};border-radius:8px;background:{c};")

    def _open_picker(self):
        host = self.window()
        picker = ColorPickerOverlay(host, saved_store=self._store)
        picker.color_committed.connect(self._apply_committed)
        picker.color_committed.connect(lambda *_: picker.deleteLater())
        picker.cancelled.connect(picker.deleteLater)
        picker.open_for(self._current)

    def _apply_committed(self, hex_):
        self._current = hex_; self._refresh(); self.color_picked.emit(hex_)
