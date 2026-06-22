"""Floating container for the portable Settings panel over the overlay.

Wraps an injected content widget (the app's real SettingsTab, reparented in)
with a dim scrim + a titled panel + a close button, and emits ``closed`` on the
X button or Esc. ``release_content`` detaches the content so the caller can
restore it to the main window's tab stack before this container is destroyed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame


class PortableSettingsContainer(QWidget):
    closed = Signal()

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._content = content
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        panel = QFrame(self)
        panel.setObjectName("portable_settings_panel")
        panel.setStyleSheet(
            "#portable_settings_panel{background:#141824;border:1px solid #232a3a;"
            "border-radius:12px;}")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 10, 6)
        title = QLabel("Settings"); title.setStyleSheet("color:#e7ecf3;font-weight:600;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{color:#cfd6e2;border:none;background:transparent;font-size:16px;}"
            "QPushButton:hover{color:#fff;}")
        close_btn.clicked.connect(self.closed.emit)
        header.addWidget(title); header.addStretch(1); header.addWidget(close_btn)
        pv.addLayout(header)
        content.setParent(panel)
        pv.addWidget(content, 1)
        outer.addWidget(panel)

    def release_content(self) -> QWidget:
        """Detach the content widget so it survives this container's destruction."""
        c = self._content
        self._content = None
        if c is not None:
            c.setParent(None)
        return c

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 10, 16, 150))   # dim the cards behind, like the ring
        p.end()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.closed.emit()
            return
        super().keyPressEvent(e)
