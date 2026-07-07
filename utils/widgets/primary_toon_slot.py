"""PrimaryToonSlot - the Launch tab account tile's 38px primary-toon portrait.

Set state: a filled circle (portraitBg token) with a tinted race silhouette
inset to the inner 76% of the circle, ringed 3px in the toon's own accent (or
the game accent when no toon has been captured yet). Unset state: a dashed
2px ring with a transparent fill and a centered "+" glyph. A 16x16
slot-number badge rides the top-left corner in both states, drawn only once
a slot number has been assigned.

Pure paintEvent - no QGraphicsEffect (kit law: this widget's paintEvent does
QPainter(self) directly, and attaching a QGraphicsEffect to it trips Qt's
"one painter at a time" conflict).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from utils.color_math import lighten_rgb, with_alpha
from utils.theme_manager import V2_ACCENTS
from utils.toon_silhouette import paint_race_silhouette

SIZE = 38
SILHOUETTE_FRACTION = 0.76
RING_W = 3
BADGE_SIZE = 16
BADGE_CENTER = 8.0
BADGE_RING_W = 2
DASH_W = 2
GLYPH_HALF = 6
GLYPH_W = 2


def _tokens(is_dark: bool) -> dict:
    if is_dark:
        return {
            "portrait_bg": with_alpha("#000000", 0.22),
            "dashed": with_alpha("#ffffff", 0.35),
            "sub": with_alpha("#ffffff", 0.62),
            "badge_ring": with_alpha("#000000", 0.28),
        }
    return {
        "portrait_bg": with_alpha("#0f172a", 0.06),
        "dashed": with_alpha("#0f172a", 0.35),
        "sub": with_alpha("#0f172a", 0.55),
        "badge_ring": with_alpha("#ffffff", 0.75),
    }


class PrimaryToonSlot(QWidget):
    clicked = Signal()

    def __init__(self, game: str, parent=None):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        self._game = game
        self._species: str | None = None
        self._accent: str | None = None
        self._slot: int | None = None
        self._set = False
        self._is_dark = True
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(SIZE, SIZE)

    def set_toon(self, *, species: str | None, accent: str | None,
                 slot_number: int | None) -> None:
        # species=None is the UNSET (dashed) visual while still showing the
        # slot-number badge - the account tile uses this to render a dashed,
        # numbered slot before a primary toon has been captured. clear()
        # remains the fully-empty (no badge) reset.
        self._species = species
        self._accent = accent
        self._slot = slot_number
        self._set = species is not None
        self.update()

    def clear(self) -> None:
        self._set = False
        self._species = None
        self._accent = None
        self._slot = None
        self.update()

    def is_set(self) -> bool:
        return self._set

    def set_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def _emit_click(self) -> None:
        self.clicked.emit()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        t = _tokens(self._is_dark)
        game_accent = V2_ACCENTS[self._game]
        circle_rect = QRectF(0, 0, SIZE, SIZE)

        if self._set:
            self._paint_set_state(p, t, game_accent, circle_rect)
        else:
            self._paint_unset_state(p, t, circle_rect)

        if self._slot is not None:
            self._paint_slot_badge(p, t, game_accent)

        p.end()

    def _paint_set_state(self, p: QPainter, t: dict, game_accent: dict,
                          circle_rect: QRectF) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(t["portrait_bg"])
        p.drawEllipse(circle_rect)

        accent_hex = self._accent or game_accent["c"]
        inset = SIZE * (1 - SILHOUETTE_FRACTION) / 2
        sil_rect = circle_rect.adjusted(inset, inset, -inset, -inset).toRect()
        fill_hex = lighten_rgb(QColor(accent_hex), 0.5).name()
        paint_race_silhouette(p, sil_rect, self._species, fill_hex)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(accent_hex), RING_W))
        ring_rect = circle_rect.adjusted(RING_W / 2, RING_W / 2, -RING_W / 2, -RING_W / 2)
        p.drawEllipse(ring_rect)

    def _paint_unset_state(self, p: QPainter, t: dict, circle_rect: QRectF) -> None:
        p.setBrush(Qt.NoBrush)
        pen = QPen(t["dashed"], DASH_W, Qt.DashLine)
        p.setPen(pen)
        ring_rect = circle_rect.adjusted(DASH_W / 2, DASH_W / 2, -DASH_W / 2, -DASH_W / 2)
        p.drawEllipse(ring_rect)

        cx, cy = SIZE / 2, SIZE / 2
        glyph_pen = QPen(t["sub"], GLYPH_W, Qt.SolidLine, Qt.RoundCap)
        p.setPen(glyph_pen)
        p.drawLine(QPointF(cx - GLYPH_HALF, cy), QPointF(cx + GLYPH_HALF, cy))
        p.drawLine(QPointF(cx, cy - GLYPH_HALF), QPointF(cx, cy + GLYPH_HALF))

    def _paint_slot_badge(self, p: QPainter, t: dict, game_accent: dict) -> None:
        badge_rect = QRectF(0, 0, BADGE_SIZE, BADGE_SIZE)
        badge_rect.moveCenter(QPointF(BADGE_CENTER, BADGE_CENTER))

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(game_accent["b"]))
        p.drawEllipse(badge_rect)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(t["badge_ring"], BADGE_RING_W))
        ring_rect = badge_rect.adjusted(BADGE_RING_W / 2, BADGE_RING_W / 2,
                                         -BADGE_RING_W / 2, -BADGE_RING_W / 2)
        p.drawEllipse(ring_rect)

        p.setPen(QColor("#ffffff"))
        font = p.font()
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(badge_rect, Qt.AlignCenter, str(self._slot))
