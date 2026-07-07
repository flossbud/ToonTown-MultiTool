"""Section empty-state placeholder shown when a game has zero accounts.

v2 pinwheel reskin: a 64x64 ringed portrait (game-accent ring, tinted person
glyph), a title/sub column using the v2 inset tokens, and a solid game-accent
CTA pill (replaces the old neutral ghost chip)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from utils.color_math import alpha, lighten_rgb
from utils.theme_manager import V2_ACCENTS, get_v2_tokens

_SHORT = {"ttr": "TTR", "cc": "CC"}
PORTRAIT_SIZE = 64


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
        outer.setContentsMargins(20, 26, 20, 30)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignHCenter)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(PORTRAIT_SIZE, PORTRAIT_SIZE)
        outer.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        outer.addSpacing(13)

        self.title_label = QLabel(f"No {_SHORT[game]} accounts yet")
        self.title_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.title_label)
        outer.addSpacing(5)

        self.subtitle_label = QLabel(
            "Add an account to launch directly into the game, or open the "
            "official launcher above if you just want to update."
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMaximumWidth(330)
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.subtitle_label, alignment=Qt.AlignCenter)
        outer.addSpacing(16)

        self.cta_btn = QPushButton(f"+ Add {_SHORT[game]} Account")
        self.cta_btn.setCursor(Qt.PointingHandCursor)
        self.cta_btn.clicked.connect(self.add_clicked.emit)
        outer.addWidget(self.cta_btn, alignment=Qt.AlignCenter)

        self.apply_theme(get_theme_colors(True))

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string from the legacy theme dict `c`."""
        is_dark = QColor(c["text_primary"]).lightnessF() > 0.5
        t = get_v2_tokens(is_dark)
        accent = V2_ACCENTS.get(self._game, V2_ACCENTS["blue"])

        portrait_bg = alpha("#000000", 0.22) if is_dark else alpha("#0f172a", 0.06)
        glyph_color = lighten_rgb(QColor(accent["c"]), 0.5).name()

        self.icon_label.setPixmap(_person_pixmap(glyph_color))
        self.icon_label.setStyleSheet(
            f"QLabel {{ background: {portrait_bg}; border: 4px solid {accent['c']};"
            f" border-radius: {PORTRAIT_SIZE // 2}px; }}"
        )
        self.title_label.setStyleSheet(
            f"color: {t['title']}; font-weight: 700; font-size: 15px;"
        )
        self.subtitle_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px;"
        )
        cta_hover = lighten_rgb(QColor(accent["c"]), 0.12).name()
        self.cta_btn.setStyleSheet(
            "QPushButton {"
            f" background: {accent['c']};"
            " color: #ffffff;"
            f" border: 1px solid {accent['b']};"
            " border-radius: 17px; padding: 9px 20px; font-size: 13px;"
            " font-weight: 700;"
            "}"
            "QPushButton:hover {"
            f" background: {cta_hover};"
            "}"
        )
