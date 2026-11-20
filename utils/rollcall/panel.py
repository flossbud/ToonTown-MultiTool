"""The installer's Customize panel: the five choices the old wizard asked,
in one list, sliding in from the right over the crew.

Keep-Alive keeps its consent step: turning it on does not flip the switch,
it opens the consent block under the row, and only "I understand, enable"
turns it on. Turning it off asks nothing.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from utils.rollcall import fonts, motion, paint
from utils.rollcall import tokens as T
from utils.rollcall.controls import PAD, RcButton, RcSwitch
from utils.rollcall.engine import InstallOptions

# The shipped consent wording. Do not paraphrase.
KEEP_ALIVE_CONSENT = (
    "The use of Keep-Alive and other automation tools is against TTR and CC ToS, "
    "and thus is disabled by default. Enable at your own risk."
)

_SIDE = 22
_TOP = 50
_BOTTOM = 20
_ROW_PAD_X = 12
_ROW_PAD_Y = 8
_ROW_MIN = 46


class CustomizePanel(QWidget):
    """440 wide, full height, anchored to the stage's right edge."""

    done = Signal()
    change_location = Signal()
    changed = Signal()

    def __init__(self, stage: QWidget, options: InstallOptions, radius: int):
        super().__init__(stage)
        self._stage = stage
        self._radius = radius
        self._options = options
        self._asking = False
        self._open = False
        self._slide = motion.Tween(1.02)         # translateX as a fraction of the width
        self._consent_fade = motion.Tween(0.0)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._change = RcButton.neutral("Change", small=True, parent=self)
        self._change.clicked.connect(self.change_location.emit)
        self._desktop = RcSwitch(options.desktop_shortcut, name="Desktop shortcut", parent=self)
        self._start = RcSwitch(options.start_menu, name="Start Menu entry", parent=self)
        self._updates = RcSwitch(options.check_updates,
                                 name="Check for updates at startup", parent=self)
        self._keep_alive = RcSwitch(options.keep_alive, keep_alive=True,
                                    name="Keep-Alive", parent=self)
        self._desktop.clicked.connect(lambda: self._flip(self._desktop, "desktop_shortcut"))
        self._start.clicked.connect(lambda: self._flip(self._start, "start_menu"))
        self._updates.clicked.connect(lambda: self._flip(self._updates, "check_updates"))
        self._keep_alive.clicked.connect(self._on_keep_alive)
        self._accept = RcButton.warn("I understand, enable", parent=self)
        self._decline = RcButton.neutral("Decline", small=True, parent=self)
        self._accept.clicked.connect(self._on_accept)
        self._decline.clicked.connect(self._on_decline)
        self._done = RcButton.neutral("Done", parent=self)
        self._done.clicked.connect(self.done.emit)

        self._consent_block = paint.TextBlock(
            KEEP_ALIVE_CONSENT, fonts.ui(11, 400), T.WARN_TEXT,
            T.PANEL_W - 2 * _SIDE - 2 * _ROW_PAD_X, 11 * 1.45)
        self._rows: list[tuple] = []
        self._card = QRectF()
        self._consent_rect = QRectF()

        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)
        self.resize(T.PANEL_W, stage.height())
        self._lay_out()
        self._place()
        self.hide()

    # ── State ──────────────────────────────────────────────────────────────

    def options(self) -> InstallOptions:
        return self._options

    def set_directory(self, directory: str) -> None:
        self._options = self._options.with_(directory=directory)
        self._lay_out()
        self.changed.emit()
        self.update()

    def is_open(self) -> bool:
        return self._open

    def consent_showing(self) -> bool:
        return self._asking

    def set_open(self, is_open: bool, animate: bool = True) -> None:
        if is_open == self._open:
            return
        self._open = is_open
        if is_open:
            self.show()
            self.raise_()
            lights = getattr(self._stage, "lights", None)
            if lights is not None:
                lights.raise_()         # minimize and close stay reachable
        target = 0.0 if is_open else 1.02
        if animate and not motion.is_reduced():
            self._slide.to(target, T.PANEL_MS, T.EASE_SETTLE)
            self._ticker.start()
        else:
            self._slide.snap(target)
            if not is_open:
                self.hide()
        self._place()

    def _flip(self, switch: RcSwitch, name: str) -> None:
        switch.set_on(not switch.is_on())
        self._options = self._options.with_(**{name: switch.is_on()})
        self.changed.emit()

    def _on_keep_alive(self) -> None:
        if self._keep_alive.is_on():
            # Off needs no confirmation.
            self._keep_alive.set_on(False)
            self._options = self._options.with_(keep_alive=False)
            self.changed.emit()
            return
        self._set_asking(not self._asking)

    def _on_accept(self) -> None:
        self._keep_alive.set_on(True)
        self._options = self._options.with_(keep_alive=True)
        self._set_asking(False)
        self.changed.emit()

    def _on_decline(self) -> None:
        self._set_asking(False)

    def _set_asking(self, asking: bool) -> None:
        self._asking = asking
        if asking:
            self._consent_fade.restart(0.0, 1.0, 260, T.EASE_SETTLE)
            self._ticker.start()
        self._lay_out()
        self.update()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _lay_out(self) -> None:
        width = T.PANEL_W - 2 * _SIDE
        x0 = float(_SIDE)
        y = float(_TOP)
        rows = []

        def row(title, sub, mono, control):
            nonlocal y
            height = _ROW_MIN
            if sub:
                height = max(_ROW_MIN, _ROW_PAD_Y * 2 + 16 + 2 + 14)
            rect = QRectF(x0, y, width, height)
            rows.append((rect, title, sub, mono))
            visual_w = control.width() - 2 * PAD
            visual_h = control.height() - 2 * PAD
            control.move(round(rect.right() - _ROW_PAD_X - visual_w) - PAD,
                         round(rect.center().y() - visual_h / 2) - PAD)
            y += height

        row("Install location", self._options.directory, True, self._change)
        row("Desktop shortcut", "", False, self._desktop)
        row("Start Menu entry", "", False, self._start)
        row("Check for updates at startup", "", False, self._updates)
        row("Keep-Alive", "Press a key on idle background toons.", False, self._keep_alive)
        if self._asking:
            text_h = self._consent_block.height
            height = 10 + text_h + 9 + 28 + 12
            self._consent_rect = QRectF(x0, y, width, height)
            button_y = y + 10 + text_h + 9
            self._accept.move(round(x0 + _ROW_PAD_X) - PAD, round(button_y) - PAD)
            self._decline.move(
                round(x0 + _ROW_PAD_X + self._accept.width() - 2 * PAD + 6) - PAD,
                round(button_y) - PAD)
            y += height
        else:
            self._consent_rect = QRectF()
        self._accept.setVisible(self._asking)
        self._decline.setVisible(self._asking)
        self._rows = rows
        self._card = QRectF(x0, _TOP, width, y - _TOP)
        self._done.move(
            T.PANEL_W - _SIDE - (self._done.width() - 2 * PAD) - PAD,
            self.height() - _BOTTOM - (self._done.height() - 2 * PAD) - PAD)

    def _place(self) -> None:
        stage = self._stage
        offset = self._slide.value() * T.PANEL_W
        self.setGeometry(round(stage.width() - T.PANEL_W + offset), 0,
                         T.PANEL_W, stage.height())

    def _on_tick(self) -> None:
        self._place()
        self.update()
        if not (self._slide.active() or self._consent_fade.active()):
            self._ticker.stop()
            if not self._open:
                self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._lay_out()

    # ── Painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        # The stage's rounded corners, in this widget's coordinates.
        stage_shape = paint.rounded_path(
            QRectF(-self.x(), 0, self._stage.width(), self._stage.height()), self._radius)
        body = QPainterPath()
        body.addRect(QRectF(self.rect()))
        p.setPen(Qt.NoPen)
        p.setBrush(T.PANEL_BG)
        p.drawPath(body.intersected(stage_shape))
        p.fillRect(QRectF(0, 0, 1, self.height()), T.white(0.12))

        card = paint.rounded_path(self._card, 9)
        p.setBrush(T.CARD_BG)
        p.drawPath(card)
        if not self._consent_rect.isNull():
            consent = QPainterPath()
            consent.addRect(self._consent_rect)
            p.setBrush(T.WARN_BG)
            p.drawPath(consent.intersected(card))
            p.fillRect(QRectF(self._consent_rect.x(), self._consent_rect.y(),
                              self._consent_rect.width(), 1), T.WARN_BORDER)
            self._consent_block.draw(
                p, self._consent_rect.x() + _ROW_PAD_X, self._consent_rect.y() + 10,
                max(0.0, min(1.0, self._consent_fade.value())))
        for i, (rect, title, sub, mono) in enumerate(self._rows):
            if i:
                p.fillRect(QRectF(rect.x(), rect.y(), rect.width(), 1), T.CARD_DIVIDER)
            text_x = rect.x() + _ROW_PAD_X
            text_w = rect.width() - 2 * _ROW_PAD_X - 80
            if sub:
                top = rect.center().y() - (16 + 2 + 14) / 2
                paint.draw_text_line(p, title, fonts.ui(13, 600), QColor("#ffffff"),
                                     QRectF(text_x, top, text_w, 16))
                font = fonts.mono(10, 500) if mono else fonts.ui(11, 400)
                paint.draw_text_line(p, paint.elide(sub, font, text_w), font, T.TEXT_MUTED,
                                     QRectF(text_x, top + 18, text_w, 14))
            else:
                paint.draw_text_line(p, title, fonts.ui(13, 600), QColor("#ffffff"),
                                     QRectF(text_x, rect.y(), text_w + 60, rect.height()))
        p.setBrush(Qt.NoBrush)
        p.setPen(T.CARD_BORDER)
        p.drawRoundedRect(self._card.adjusted(0.5, 0.5, -0.5, -0.5), 8.5, 8.5)
        p.end()

    def mousePressEvent(self, event) -> None:
        event.accept()          # the panel never drags the window
