"""Hand-painted miniature card used as the live preview pane inside
ToonCustomizationDialog. Reads from a draft dict, consults the
resolver helpers, never touches the manager."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from utils.toon_customization_resolve import (
    resolve_accent,
    resolve_body,
    resolve_portrait_brush,
    resolve_portrait_pattern,
)
from utils.toon_pattern_assets import tinted_pattern_pixmap


_PREVIEW_W = 360
_PREVIEW_H = 72

# Brand color defaults mirror tabs/multitoon/_compact_layout.set_card_brand
_TTR_BRAND = "#4A8FE7"
_CC_BRAND = "#F26D21"
_SLOT_DEFAULT_BG = "#4a4a4a"
_CARD_BG = "#1a1d29"
_TEXT = "#e8e8f0"
_TEXT_DIM = "#9a9aa8"


def _brand_fallback(game: str) -> QColor:
    if game == "ttr":
        return QColor(_TTR_BRAND)
    if game == "cc":
        return QColor(_CC_BRAND)
    return QColor(_SLOT_DEFAULT_BG)


class CardPreviewWidget(QWidget):
    def __init__(self, game: str, toon_name: str, draft: dict, parent=None):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._draft: dict = dict(draft)
        self.setMinimumSize(_PREVIEW_W, _PREVIEW_H)
        self.setMaximumSize(_PREVIEW_W, _PREVIEW_H)

    def draft(self) -> dict:
        return dict(self._draft)

    def set_draft(self, draft: dict) -> None:
        self._draft = dict(draft)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # Card background
        body = resolve_body(self._draft)
        card_bg = QColor(_CARD_BG)
        if body is not None:
            mix = QColor(body)
            mix.setAlpha(64)
            p.fillRect(rect, card_bg)
            p.fillRect(rect, mix)
        else:
            p.fillRect(rect, card_bg)

        # Accent stripe (top 3 px)
        accent = resolve_accent(self._draft, _brand_fallback(self._game))
        p.fillRect(QRect(rect.left(), rect.top(), rect.width(), 3), accent)

        # Portrait circle (40 px, vertically centered, 10 px from left)
        circle_d = 40
        circle_rect = QRect(
            10,
            (rect.height() - circle_d) // 2 + 1,
            circle_d,
            circle_d,
        )
        portrait_brush = resolve_portrait_brush(
            self._draft, QColor(_SLOT_DEFAULT_BG)
        )
        p.setPen(Qt.NoPen)
        p.setBrush(portrait_brush)
        p.drawEllipse(circle_rect)

        pattern = resolve_portrait_pattern(self._draft)
        if pattern is not None:
            name, color = pattern
            pm = tinted_pattern_pixmap(name, color, tile_size=24)
            if not pm.isNull():
                path = QPainterPath()
                path.addEllipse(circle_rect)
                p.save()
                p.setClipPath(path)
                # Tile the pattern across the circle area.
                for y in range(circle_rect.top(), circle_rect.bottom() + 1, 24):
                    for x in range(circle_rect.left(), circle_rect.right() + 1, 24):
                        p.drawPixmap(x, y, pm)
                p.restore()

        # Toon name
        p.setPen(QColor(_TEXT))
        f: QFont = p.font()
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            QRect(60, 6, rect.width() - 70, 24),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._toon_name or "Toon",
        )

        # Chip on right (outlined pill, accent border + text)
        chip_text = "TTR" if self._game == "ttr" else ("CC" if self._game == "cc" else "")
        if chip_text:
            chip_w = 38
            chip_h = 18
            chip_rect = QRect(
                rect.width() - chip_w - 8,
                (rect.height() - chip_h) // 2,
                chip_w,
                chip_h,
            )
            p.setPen(accent)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(chip_rect, 9, 9)
            f2: QFont = p.font()
            f2.setPixelSize(10)
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(chip_rect, Qt.AlignCenter, chip_text)

        # Subtitle row
        p.setPen(QColor(_TEXT_DIM))
        f3: QFont = p.font()
        f3.setPixelSize(11)
        f3.setBold(False)
        p.setFont(f3)
        p.drawText(
            QRect(60, rect.height() - 26, rect.width() - 70, 20),
            Qt.AlignVCenter | Qt.AlignLeft,
            "Live preview",
        )
        p.end()
