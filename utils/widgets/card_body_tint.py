"""Semi-transparent body-tint overlay for the per-toon card.

Lives beneath the toon controls (Z-order via lower()) and reads its
color from `ToonCustomizationsManager`. Painted at ~25% opacity so
theme contrast survives.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


_TINT_OPACITY = 64  # /255 ~= 25%


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
        c = QColor(self._color)
        c.setAlpha(_TINT_OPACITY)
        p.fillRect(self.rect(), c)
        p.end()
