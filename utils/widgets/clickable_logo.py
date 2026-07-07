"""ClickableLogo — the wordmark as a Credits button: a pixmap QLabel with a
`clicked` signal, a hover highlight, and an `active` state (lit while Credits
is open). Custom-painted highlight (no QGraphicsEffect)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel


class ClickableLogo(QLabel):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self._active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        if self._hover or self._active:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            a = 0.08 if self._active else 0.04
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(255 * a)))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)
            p.end()
        super().paintEvent(e)   # draws the pixmap on top
