"""Section empty-state placeholder shown when a game has zero accounts."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


_ACCENT = {"ttr": "#0077ff", "cc": "#F26D21"}
_ICON_TINT = {"ttr": ("rgba(74,143,231,0.12)", "rgba(74,143,231,0.25)", "#88c0d0"),
              "cc":  ("rgba(242,109,33,0.12)", "rgba(242,109,33,0.3)", "#F2A06D")}
_SHORT = {"ttr": "TTR", "cc": "CC"}


def _person_pixmap(color: str, size: int = 30) -> QPixmap:
    """Render the person silhouette to a QPixmap via QSvgRenderer.
    Qt's QLabel rich-text engine does not honour inline SVG, so we rasterize."""
    svg_bytes = QByteArray((
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
        f' fill="none" stroke="{color}" stroke-width="2"'
        f' stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
        f'<circle cx="12" cy="7" r="4"/>'
        f'</svg>'
    ).encode("utf-8"))
    renderer = QSvgRenderer(svg_bytes)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


class EmptyState(QWidget):
    add_clicked = Signal()

    def __init__(self, game: str, parent: QWidget | None = None):
        super().__init__(parent)
        bg, border, fg = _ICON_TINT[game]
        accent = _ACCENT[game]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 30, 20, 30)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignHCenter)

        icon = QLabel()
        icon.setPixmap(_person_pixmap(fg))
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(56, 56)
        icon.setStyleSheet(
            f"QLabel {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 14px; color: {fg}; }}"
        )
        outer.addWidget(icon, alignment=Qt.AlignCenter)
        outer.addSpacing(14)

        self.title_label = QLabel(f"No {_SHORT[game]} accounts yet")
        self.title_label.setStyleSheet("color: #fff; font-weight: 700; font-size: 15px;")
        self.title_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.title_label)
        outer.addSpacing(6)

        sub = QLabel(
            "Add an account to launch directly into the game, or open the "
            "official launcher above if you just want to update."
        )
        sub.setWordWrap(True)
        sub.setMaximumWidth(320)
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color: #8a9bb8; font-size: 12px;")
        outer.addWidget(sub, alignment=Qt.AlignCenter)
        outer.addSpacing(18)

        self.cta_btn = QPushButton(f"+ Add {_SHORT[game]} Account")
        self.cta_btn.setCursor(Qt.PointingHandCursor)
        self.cta_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: white; border: none;"
            f" border-radius: 6px; padding: 8px 18px; font-size: 13px;"
            f" font-weight: 600; }}"
        )
        self.cta_btn.clicked.connect(self.add_clicked.emit)
        outer.addWidget(self.cta_btn, alignment=Qt.AlignCenter)
