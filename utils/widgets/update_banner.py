"""Thin non-modal banner shown between the main-window header and the tab
switcher when an update is available. Click body -> opens the update dialog.
Click x -> hides for this session only (banner reappears on next startup if the
update is still applicable)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFontMetrics, QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from utils.icon_factory import make_x_icon


BANNER_TEXT = "⬆  A new update is available - click to update"

_GRADIENT = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
    "stop:0 #b1005e, stop:0.5 #6024a8, stop:1 #1e50c8)"
)


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

        self._close_btn = QPushButton()
        self._close_btn.setObjectName("update_banner_close")
        self._close_btn.setIcon(make_x_icon(14, QColor("#ffffff")))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setToolTip("Dismiss")
        self._close_btn.setAccessibleName("Dismiss update notice")
        self._close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._close_btn, 0)

        self.apply_theme()
        self.hide()

    def apply_theme(self, colors: Optional[dict] = None) -> None:
        """Apply the banner's gradient styling. `colors` is accepted for call
        symmetry with the rest of _apply_full_theme and for a future light/dark
        divergence; the gradient is theme-independent for now."""
        self.setStyleSheet(
            f"""
            QFrame#update_banner {{
                background: {_GRADIENT};
                border: none;
            }}
            QLabel#update_banner_label {{
                background: transparent;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#update_banner_close {{
                background: transparent;
                border: none;
                padding: 0;
            }}
            QPushButton#update_banner_close:hover {{
                background: rgba(255, 255, 255, 0.18);
                border-radius: 4px;
            }}
            """
        )
        self._refresh_label()

    def show_for_release(self, release_info: dict) -> None:
        self._release = release_info
        self._refresh_label()
        self.show()

    def _refresh_label(self) -> None:
        if self._release is None:
            self._label.setText("")
            return
        fm = QFontMetrics(self._label.font())
        avail = max(0, self._label.width() - 12)
        self._label.setText(
            fm.elidedText(BANNER_TEXT, Qt.ElideRight, avail) if avail > 0 else BANNER_TEXT
        )

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
