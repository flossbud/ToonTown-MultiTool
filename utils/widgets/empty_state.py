"""Section empty-state placeholder shown when a game has zero accounts."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


_SHORT = {"ttr": "TTR", "cc": "CC"}


def _rgba(hex_color: str, alpha: float) -> str:
    """Convert a `#rrggbb` to an `rgba(r,g,b,a)` string."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


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
        from utils.theme_manager import get_theme_colors
        self._game = game

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 30, 20, 30)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignHCenter)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(56, 56)
        outer.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        outer.addSpacing(14)

        self.title_label = QLabel(f"No {_SHORT[game]} accounts yet")
        self.title_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.title_label)
        outer.addSpacing(6)

        self.subtitle_label = QLabel(
            "Add an account to launch directly into the game, or open the "
            "official launcher above if you just want to update."
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMaximumWidth(320)
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.subtitle_label, alignment=Qt.AlignCenter)
        outer.addSpacing(18)

        self.cta_btn = QPushButton(f"+ Add {_SHORT[game]} Account")
        self.cta_btn.setCursor(Qt.PointingHandCursor)
        self.cta_btn.clicked.connect(self.add_clicked.emit)
        outer.addWidget(self.cta_btn, alignment=Qt.AlignCenter)

        self.apply_theme(get_theme_colors(True))

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string from the theme dict `c`."""
        pill_hex = c["game_pill_ttr"] if self._game == "ttr" else c["game_pill_cc"]
        # Derive low-alpha icon tints from the pill color.
        tint_bg = _rgba(pill_hex, 0.12)
        tint_border = _rgba(pill_hex, 0.30)

        self.icon_label.setPixmap(_person_pixmap(pill_hex))
        self.icon_label.setStyleSheet(
            f"QLabel {{ background: {tint_bg}; border: 1px solid {tint_border};"
            f" border-radius: 14px; color: {pill_hex}; }}"
        )
        self.title_label.setStyleSheet(
            f"color: {c['text_primary']}; font-weight: 700; font-size: 15px;"
        )
        self.subtitle_label.setStyleSheet(
            f"color: {c['text_muted']}; font-size: 12px;"
        )
        self.cta_btn.setStyleSheet(
            "QPushButton {"
            " background: transparent;"
            f" color: {c['text_secondary']};"
            f" border: 1px solid {c['border_muted']};"
            " border-radius: 6px; padding: 8px 18px; font-size: 13px;"
            " font-weight: 600;"
            "}"
            "QPushButton:hover {"
            f" background: {c['bg_card_inner_hover']};"
            f" color: {c['text_primary']};"
            f" border-color: {c['border_card']};"
            "}"
        )
