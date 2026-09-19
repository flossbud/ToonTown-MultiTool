"""The hero stage (handoff §4.1b): greeting, launch party, and the one CTA.

Two modes. Normal greets the main toon and offers Play. Blocked replaces the
copy column with a credential reason and its action, and removes Play — when
nothing can launch, "Welcome back / PLAY 4 TOONS" is a lie (spec Q6).

The party count appears on the Play button and nowhere else. That is a design
contract, not a stylistic preference: pinned by test_the_count_appears_nowhere.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from utils.asset_paths import asset_path
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.game_selector import ART

COPY_LEFT = 26
COPY_W = 340
PLAY_H = 46
CREW_LEFT = 352
HERO_RADIUS = 9

GAME_SHORT = {"ttr": "TTR", "cc": "CC"}


class HeroStage(QFrame):
    play_clicked = Signal()
    official_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_hero")
        self._game = "ttr"
        self._is_dark = True
        self._main: str | None = None
        self._party: list[str] = []
        self._blocked: str | None = None
        self._on_action = None
        self._art = {g: QPixmap(asset_path(ART[g])) for g in ("ttr", "cc")}

        self.copy = QWidget(self)
        self.copy.setObjectName("gs_hero_copy")
        self.copy.setStyleSheet(
            "#gs_hero_copy { background: transparent; }")
        col = QVBoxLayout(self.copy)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        col.addStretch()

        self.greeting = QLabel(self.copy)
        self.greeting.setWordWrap(True)
        col.addWidget(self.greeting)

        self.names = QLabel(self.copy)
        self.names.setWordWrap(True)
        self.names.setFixedHeight(32)
        col.addWidget(self.names)

        self.play_button = QPushButton(self.copy)
        self.play_button.setFixedHeight(PLAY_H)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.clicked.connect(self._on_play)
        col.addWidget(self.play_button, 0, Qt.AlignLeft)

        self.blocked_label = QLabel(self.copy)
        self.blocked_label.setWordWrap(True)
        self.blocked_label.setVisible(False)
        col.addWidget(self.blocked_label)

        self.blocked_button = QPushButton(self.copy)
        self.blocked_button.setFixedHeight(PLAY_H)
        self.blocked_button.setCursor(Qt.PointingHandCursor)
        self.blocked_button.setVisible(False)
        self.blocked_button.clicked.connect(self._on_blocked_action)
        col.addWidget(self.blocked_button, 0, Qt.AlignLeft)

        col.addStretch()

        self.official_button = QPushButton(self)
        self.official_button.setFixedHeight(28)
        self.official_button.setCursor(Qt.PointingHandCursor)
        self.official_button.clicked.connect(self.official_clicked.emit)

        from utils.widgets.grandstand.crew_lineup import CrewLineup
        self.crew_area = CrewLineup(self)

        self.set_game("ttr")
        self.set_party([])
        self.set_main(None)
        self.apply_theme(True)

    # ── inbound ────────────────────────────────────────────────────────────

    def game(self) -> str:
        return self._game

    def set_game(self, game: str) -> None:
        if game not in ("ttr", "cc"):
            return
        self._game = game
        self.official_button.setText(f"Official {GAME_SHORT[game]} launcher")
        self.update()

    def set_main(self, toon_name: str | None) -> None:
        self._main = toon_name or None
        self.greeting.setText(
            f"Welcome back,\n{self._main}!" if self._main else "Welcome back!")

    def set_party(self, names: list[str]) -> None:
        self._party = list(names)
        n = len(self._party)
        self.names.setText(" · ".join(self._party) if n else
                           "Choose one or more toons below to build your "
                           "launch party.")
        if n == 0:
            label = "SELECT A TOON"
        elif n == 1:
            label = "PLAY 1 TOON"
        else:
            label = f"PLAY {n} TOONS"
        self.play_button.setText(label)
        self.play_button.setEnabled(n > 0)
        self._restyle_play()

    def set_lineup(self, entries: list) -> None:
        self.crew_area.set_entries(entries)

    def set_blocked(self, reason: str | None, action_text: str = "",
                    on_action=None) -> None:
        """Enter or leave blocked mode. `reason=None` restores normal mode."""
        self._blocked = reason or None
        self._on_action = on_action
        blocked = self._blocked is not None
        self.blocked_label.setText(self._blocked or "")
        self.blocked_label.setVisible(blocked)
        self.blocked_button.setText(action_text)
        self.blocked_button.setVisible(blocked and bool(action_text))
        self.greeting.setVisible(not blocked)
        self.names.setVisible(not blocked)
        self.play_button.setVisible(not blocked)
        self.official_button.setVisible(not blocked)
        self.official_button.setEnabled(not blocked)

    def is_blocked(self) -> bool:
        return self._blocked is not None

    # ── readouts (test surface) ────────────────────────────────────────────

    def greeting_text(self) -> str:
        return self.greeting.text().replace("\n", " ")

    def names_text(self) -> str:
        return self.names.text()

    def blocked_text(self) -> str:
        return self.blocked_label.text()

    def play_label(self) -> str:
        return self.play_button.text()

    def play_enabled(self) -> bool:
        return self.play_button.isEnabled()

    # ── internals ──────────────────────────────────────────────────────────

    def _on_play(self) -> None:
        if self.play_button.isEnabled():
            self.play_clicked.emit()

    def _on_blocked_action(self) -> None:
        if callable(self._on_action):
            self._on_action()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        ink = gp.hero_ink(is_dark)
        self.greeting.setStyleSheet(
            f"color: {ink['greeting'].name()}; font-family: 'Fredoka';"
            " font-size: 29px; font-weight: 700;")
        self.names.setStyleSheet(
            f"color: {ink['names'].name(QColor.HexArgb)}; font-size: 12px;")
        self.blocked_label.setStyleSheet(
            f"color: {ink['blocked'].name()}; font-size: 14px;"
            " font-weight: 600;")
        g = gp.hero_ghost_button(is_dark)
        ghost = (f" background: {g['bg'].name(QColor.HexArgb)};"
                 f" color: {g['ink'].name()};"
                 f" border: 1px solid {g['border'].name(QColor.HexArgb)};")
        self.blocked_button.setStyleSheet(
            "QPushButton {" + ghost + " border-radius: 8px; padding: 0 18px;"
            " font-size: 13px; font-weight: 700; }")
        self.official_button.setStyleSheet(
            "QPushButton {" + ghost + " border-radius: 14px; padding: 0 11px;"
            " font-size: 11px; font-weight: 500; }")
        self._restyle_play()
        self.update()

    def _restyle_play(self) -> None:
        d = gp.play_button(self.play_button.isEnabled(), self._is_dark)
        hover = gp.play_button(True, self._is_dark)["border"].name()
        self.play_button.setStyleSheet(
            "QPushButton {"
            f" background: {d['bg'].name(QColor.HexArgb)};"
            f" color: {d['ink'].name(QColor.HexArgb)};"
            f" border: 1px solid {d['border'].name(QColor.HexArgb)};"
            " border-radius: 8px; padding: 0 22px; font-size: 15px;"
            " font-weight: 800; letter-spacing: 0.9px; }"
            f"QPushButton:hover:enabled {{ background: {hover}; }}")
        # Qt stylesheets cannot express the design's `box-shadow: 0 3px 0`, so
        # the CTA's lift is a zero-blur drop shadow. Disabled loses it entirely
        # (handoff §4.1b).
        if d["shadow"] is None:
            self.play_button.setGraphicsEffect(None)
            return
        effect = QGraphicsDropShadowEffect(self.play_button)
        effect.setOffset(0, 3)
        effect.setBlurRadius(0)
        effect.setColor(d["shadow"])
        self.play_button.setGraphicsEffect(effect)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.copy.setGeometry(COPY_LEFT, 0, COPY_W, self.height())
        self.official_button.adjustSize()
        bw = self.official_button.width()
        self.official_button.move(self.width() - bw - 14, 14)
        self.crew_area.setGeometry(CREW_LEFT, 0,
                                   max(0, self.width() - CREW_LEFT), self.height())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.save()
        p.setClipRect(r)
        p.setPen(Qt.NoPen)
        p.setBrush(gp.hero_base(self._game, self._is_dark))
        p.drawRoundedRect(r, HERO_RADIUS, HERO_RADIUS)

        art = self._art.get(self._game)
        if art is not None and not art.isNull():
            scaled = art.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            y = self.height() - scaled.height() if self._game == "cc" else \
                (self.height() - scaled.height()) // 2
            p.drawPixmap(0, y, scaled)

        grad = QLinearGradient(0, 0, self.width(), 0)
        for pos, colour in gp.hero_scrim(self._game, self._is_dark):
            grad.setColorAt(pos, colour)
        p.setBrush(grad)
        p.drawRoundedRect(r, HERO_RADIUS, HERO_RADIUS)
        p.restore()

        p.setBrush(Qt.NoBrush)
        p.setPen(Qt.PenStyle.SolidLine)
        p.end()
