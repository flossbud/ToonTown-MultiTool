"""Thin non-modal banner shown above the main-window header when an
update is available. Click body -> opens the update dialog. Click x ->
hides for this session only (banner reappears on next startup if the
update is still applicable)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


WIDTH_BREAKPOINT_PX = 800


class UpdateBanner(QFrame):
    clicked = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("update_banner")
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)
        self._release: Optional[dict] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setObjectName("update_banner_label")
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        self._label.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._label, 1)

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("update_banner_close")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._close_btn, 0)

        self.hide()

    def show_for_release(self, release_info: dict) -> None:
        self._release = release_info
        self._refresh_label()
        self.show()

    def _refresh_label(self) -> None:
        if self._release is None:
            self._label.setText("")
            return
        tag = self._release.get("tag_name", "")
        if self.width() >= WIDTH_BREAKPOINT_PX:
            text = f"⬆  {tag} is available — click to view"
        else:
            text = "⬆  Update available — tap"
        fm = QFontMetrics(self._label.font())
        avail = max(0, self._label.width() - 12)
        self._label.setText(fm.elidedText(text, Qt.ElideRight, avail) if avail > 0 else text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_label()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            if not self._close_btn.geometry().contains(event.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _on_close_clicked(self) -> None:
        self.hide()
        self.dismissed.emit()
