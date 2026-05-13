"""OverflowPopup — custom QFrame popup that replaces QMenu in the chip rail.

Hosts a vertical list of clickable rows. Paints itself with an animatable
`_scale` factor so the open animation grows from the trigger corner.
Click-outside or Esc dismisses (handled by the parent's event filter).
"""
from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import QEvent, QPoint, Qt, Property
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QFrame, QPushButton, QVBoxLayout,
)


class OverflowPopup(QFrame):
    """A frameless popup window. Use `add_action` to populate, then
    `show_at(anchor)` to display below an anchor widget.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overflow_popup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self.rows: List[QPushButton] = []
        self._scale = 1.0
        self._anchor_corner = (1.0, 0.0)  # top-right of popup = origin

    def add_action(self, label: str, handler: Callable[[], None]) -> None:
        row = QPushButton(label, self)
        row.setObjectName("overflow_row")
        row.setFlat(True)
        row.setMinimumHeight(28)
        row.clicked.connect(lambda _checked=False: (handler(), self.hide()))
        self.layout().addWidget(row)
        self.rows.append(row)

    def show_at(self, anchor) -> None:
        anchor_bl = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        self.adjustSize()
        # Top-right corner of popup aligns with bottom-right of anchor.
        x = anchor_bl.x() - self.width()
        y = anchor_bl.y()
        self.move(x, y)
        self.show()

    # ── Scale property (animatable) ─────────────────────────────────────
    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = float(v)
        self.update()

    scale = Property(float, _get_scale, _set_scale)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # Scale around top-right (anchor corner).
        anchor_x = self.width() * self._anchor_corner[0]
        anchor_y = self.height() * self._anchor_corner[1]
        p.translate(anchor_x, anchor_y)
        p.scale(self._scale, self._scale)
        p.translate(-anchor_x, -anchor_y)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 8, 8)
        p.fillPath(path, QColor("#2b2745"))
        p.setPen(QColor(124, 92, 255, 80))
        p.drawPath(path)
        p.end()
        # Let child widgets (the rows) paint normally on top via super().
        super().paintEvent(event)
