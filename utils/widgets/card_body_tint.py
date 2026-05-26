"""Body-tint overlay for the per-toon card.

Lives beneath the toon controls (Z-order via lower()) and reads its
color from `ToonCustomizationsManager`. Painted at full opacity so the
on-card color matches the value picked in the customization dialog. The
overlay only renders when the user has explicitly chosen a non-default
body color; the Default option hides the widget entirely.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class CardBodyTint(QWidget):
    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        # Don't intercept clicks meant for the toon controls beneath.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)
        p.end()
