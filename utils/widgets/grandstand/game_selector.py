"""The two-card game selector (handoff §4.1a).

Each card carries its game's backdrop art, dimmed and desaturated when
inactive, so switching games repaints the identity of the whole tab. Art is
painted rather than styled because QSS cannot express `saturate()`.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from utils.asset_paths import asset_path
from utils.widgets.grandstand import palette as gp

ART = {"ttr": "ttr-banner-pattern.png", "cc": "cc-banner-skyline.png"}
LOGO = {"ttr": "ttr.png", "cc": "cc.png"}
NAME = {"ttr": "TOONTOWN REWRITTEN", "cc": "CORPORATE CLASH"}

CARD_RADIUS = 9
LOGO_PX = 42


def _desaturate(pm: QPixmap, amount: float) -> QPixmap:
    """Blend a pixmap toward its own luminance. `amount` 1.0 = untouched.

    Qt's grayscale conversion and compositing both run in native code, so this
    stays fast on the 1.19-megapixel Clash backdrop. A per-pixel Python loop on
    that asset costs ~300 ms at construction — a visible stall on the app's
    most-used screen. SourceAtop is used because result alpha is the
    destination's, so the source artwork's transparency survives the blend.
    The grayscale source stays opaque so painter opacity applies the same
    desaturation strength at soft, translucent edges.
    """
    if amount >= 0.999 or pm.isNull():
        return pm

    source = pm.toImage()
    gray = source.convertToFormat(QImage.Format_Grayscale8).convertToFormat(
        QImage.Format_ARGB32)
    out = QPixmap(pm)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    painter.setOpacity(1.0 - amount)
    painter.drawImage(0, 0, gray)
    painter.end()
    return out


class GameCard(QFrame):
    """Emits clicked with its game key; GameSelector forwards it as game_clicked."""

    clicked = Signal(str)

    def __init__(self, game: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game = game
        self._active = game == "ttr"
        self._is_dark = True
        self._count = 0
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(120)

        self._art = QPixmap(asset_path(ART[game]))
        # Saturation is theme-independent today; this is the inactive lookup.
        self._art_dim = _desaturate(
            self._art, gp.game_card(game, False, True)["saturation"])

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(12)

        self._logo = QLabel(self)
        pm = QPixmap(asset_path(LOGO[game]))
        if not pm.isNull():
            self._logo.setPixmap(pm.scaled(
                LOGO_PX, LOGO_PX, Qt.KeepAspectRatio,
                Qt.SmoothTransformation))
        self._logo.setFixedSize(LOGO_PX, LOGO_PX)
        # A pixmap label is still a QLabel: without this the app's global
        # QWidget background rule paints a square behind the logo.
        self._logo.setStyleSheet("background: transparent;")
        row.addWidget(self._logo, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self._name = QLabel(NAME[game], self)
        self._meta = QLabel("NO ACCOUNTS", self)
        col.addWidget(self._name)
        col.addWidget(self._meta)
        row.addLayout(col, 1)

        self._restyle()

    def game(self) -> str:
        return self._game

    def meta_text(self) -> str:
        return self._meta.text()

    def set_count(self, n: int) -> None:
        self._count = max(0, int(n))
        if self._count == 0:
            self._meta.setText("NO ACCOUNTS")
        elif self._count == 1:
            self._meta.setText("1 ACCOUNT")
        else:
            self._meta.setText(f"{self._count} ACCOUNTS")

    def set_active(self, value: bool) -> None:
        self._active = bool(value)
        self._restyle()
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._restyle()
        self.update()

    def _restyle(self) -> None:
        colors = gp.game_card(self._game, self._active, self._is_dark)
        self._name.setStyleSheet(
            f"color: {colors['name_ink'].name()}; font-size: 13px;"
            " font-weight: 800; letter-spacing: 0.13px;"
            " background: transparent;")
        self._meta.setStyleSheet(
            f"color: {colors['meta_ink'].name()}; font-size: 10px;"
            " font-weight: 600; letter-spacing: 0.8px;"
            " background: transparent;")

    def mouseReleaseEvent(self, event) -> None:
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit(self._game)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        colors = gp.game_card(self._game, self._active, self._is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        clip = QPainterPath()
        clip.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        painter.save()
        painter.setClipPath(clip)
        painter.setBrush(QBrush(colors["bg"]))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        art = self._art if self._active else self._art_dim
        if not art.isNull():
            painter.setOpacity(colors["art_opacity"])
            scaled = art.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            # CC's skyline reads from its base; TTR's pattern tiles centred.
            y = (self.height() - scaled.height() if self._game == "cc"
                 else (self.height() - scaled.height()) // 2)
            painter.drawPixmap(0, y, scaled)
            painter.setOpacity(1.0)
        painter.restore()

        painter.setBrush(Qt.NoBrush)
        painter.setPen(colors["border"])
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        if colors["inset"] is not None:
            painter.setPen(colors["inset"])
            painter.drawRoundedRect(
                rect.adjusted(1, 1, -1, -1), CARD_RADIUS - 1,
                CARD_RADIUS - 1)
        painter.end()


class GameSelector(QWidget):
    """Two cards side by side; exactly one is active."""

    game_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = "ttr"
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._cards: dict[str, GameCard] = {}
        for game in ("ttr", "cc"):
            card = GameCard(game, self)
            card.clicked.connect(self.game_clicked.emit)
            self._cards[game] = card
            row.addWidget(card, 1)
        self.set_active("ttr")

    def card(self, game: str) -> GameCard:
        return self._cards[game]

    def active(self) -> str:
        return self._active

    def set_active(self, game: str) -> None:
        if game not in self._cards:
            return
        self._active = game
        for key, card in self._cards.items():
            card.set_active(key == game)

    def set_counts(self, ttr: int, cc: int) -> None:
        self._cards["ttr"].set_count(ttr)
        self._cards["cc"].set_count(cc)

    def apply_theme(self, is_dark: bool) -> None:
        for card in self._cards.values():
            card.apply_theme(is_dark)
