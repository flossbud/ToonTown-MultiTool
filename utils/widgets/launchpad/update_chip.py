"""The header's update chip. It sits where the session status sits and
replaces it while it has something to say: an update is ready, it is
downloading, a restart will finish it, a manual check is running or just
answered, or What's new can be reopened.

28 high, fully rounded, Inter 11 / 700. The design gives the colours on the
dark header; the light header uses the same hues with ink dark enough to
read on it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from utils import update_flow
from utils.rollcall import fonts, motion, paint
from utils.rollcall import tokens as T

HEIGHT = 28
PAD_X = 11
GAP = 6
FOCUS_PAD = 4

_YELLOW, _GREEN, _RED, _QUIET = "yellow", "green", "red", "quiet"

_TONE_OF = {
    update_flow.CHIP_UPDATE: _YELLOW,
    update_flow.CHIP_DOWNLOADING: _YELLOW,
    update_flow.CHIP_WHATS_NEW: _YELLOW,
    update_flow.CHIP_RESTART: _GREEN,
    update_flow.CHIP_UP_TO_DATE: _GREEN,
    update_flow.CHIP_PAUSED: _RED,
    update_flow.CHIP_CHECK_FAILED: _RED,
    update_flow.CHIP_CHECKING: _QUIET,
}

# tone -> (border, fill, text), dark header then light header.
_DARK = {
    _YELLOW: (QColor("#e8c14d"), T.rgba(212, 160, 23, 0.16), QColor("#e8c14d")),
    _GREEN: (QColor("#56d66a"), T.rgba(61, 163, 67, 0.20), QColor("#b9f0c0")),
    _RED: (QColor("#d95757"), T.rgba(224, 82, 82, 0.18), QColor("#ffb4b4")),
    _QUIET: (T.rgba(255, 255, 255, 0.20), T.rgba(255, 255, 255, 0.06), QColor("#bbbbbb")),
}
_LIGHT = {
    _YELLOW: (QColor("#b88a0b"), T.rgba(212, 160, 23, 0.20), QColor("#6f5200")),
    _GREEN: (QColor("#2e8b3a"), T.rgba(61, 163, 67, 0.18), QColor("#1c6327")),
    _RED: (QColor("#c24545"), T.rgba(224, 82, 82, 0.14), QColor("#9a2b2b")),
    _QUIET: (T.rgba(0, 0, 0, 0.22), T.rgba(0, 0, 0, 0.05), QColor("#555555")),
}


class UpdateChip(QAbstractButton):
    """Shows one ``update_flow.Chip``; hidden when given None."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._chip: update_flow.Chip | None = None
        self._dark = True
        self._enter = motion.Tween(1.0)
        self._t0 = motion.now()
        self._keyboard_focus = False
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self.update)
        self.hide()

    def chip(self) -> update_flow.Chip | None:
        return self._chip

    def set_dark(self, is_dark: bool) -> None:
        if is_dark != self._dark:
            self._dark = bool(is_dark)
            self.update()

    def set_chip(self, chip: update_flow.Chip | None) -> None:
        previous = self._chip
        self._chip = chip
        if chip is None:
            self._ticker.stop()
            self.hide()
            return
        if previous is None or previous.kind != chip.kind:
            # A new thing to say enters: fade in and rise 7 px.
            self._enter.restart(0.0, 1.0, T.TICK_ENTER_MS, T.EASE_SETTLE)
            self._t0 = motion.now()
        self.setCursor(Qt.PointingHandCursor if chip.clickable else Qt.ArrowCursor)
        self.setAccessibleName(self._text())
        self.setFixedSize(self.sizeHint())
        animated = chip.kind in (update_flow.CHIP_UPDATE, update_flow.CHIP_CHECKING)
        if animated or self._enter.active():
            self._ticker.start()
        self.show()
        self.update()

    def _text(self) -> str:
        chip = self._chip
        if chip is None:
            return ""
        if chip.kind == update_flow.CHIP_DOWNLOADING and chip.percent >= 0:
            return f"{chip.label} {chip.percent}%"
        return chip.label

    def _lead_width(self) -> float:
        kind = self._chip.kind if self._chip else ""
        if kind == update_flow.CHIP_UPDATE:
            return 6 + GAP
        if kind == update_flow.CHIP_CHECKING:
            return 11 + GAP
        if kind == update_flow.CHIP_UP_TO_DATE:
            return 12 + GAP
        return 0.0

    def _content_width(self) -> float:
        chip = self._chip
        if chip is None:
            return 0.0
        width = self._lead_width() + paint.text_width(chip.label, fonts.ui(11, 700))
        if chip.kind == update_flow.CHIP_DOWNLOADING and chip.percent >= 0:
            # Room for three digits so the chip does not twitch as it counts.
            width += GAP + paint.text_width("100%", fonts.mono(11, 700))
        return width

    def sizeHint(self) -> QSize:
        return QSize(int(self._content_width() + 2 * PAD_X + 0.999) + 2 * FOCUS_PAD,
                     HEIGHT + 2 * FOCUS_PAD)

    def visual_width(self) -> int:
        return self.width() - 2 * FOCUS_PAD

    def mousePressEvent(self, event) -> None:
        if self._chip is not None and not self._chip.clickable:
            event.ignore()
            return
        super().mousePressEvent(event)

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = event.reason() in (
            Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(event)

    def paintEvent(self, _event) -> None:
        chip = self._chip
        if chip is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        enter = max(0.0, min(1.0, self._enter.value()))
        p.setOpacity(enter)
        if not motion.is_reduced():
            p.translate(0, (1.0 - self._enter.value()) * T.RISE_PX)
        border, fill, ink = (_DARK if self._dark else _LIGHT)[_TONE_OF.get(chip.kind, _YELLOW)]
        rect = QRectF(FOCUS_PAD, FOCUS_PAD, self.width() - 2 * FOCUS_PAD, HEIGHT)
        if chip.clickable and self.underMouse():
            fill = QColor(fill)
            fill.setAlpha(min(255, int(fill.alpha() * 1.5)))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, HEIGHT / 2, HEIGHT / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), HEIGHT / 2 - 0.5, HEIGHT / 2 - 0.5)

        x = rect.x() + PAD_X
        cy = rect.center().y()
        elapsed = motion.now() - self._t0
        if chip.kind == update_flow.CHIP_UPDATE:
            # A 6 px dot pulsing down to 30 % and back, every 1.9 s.
            phase = (elapsed % 1900.0) / 1900.0
            pulse = 1.0 if motion.is_reduced() else 1.0 - 0.7 * (1.0 - abs(2.0 * phase - 1.0))
            dot = QColor(ink)
            dot.setAlphaF(max(0.0, min(1.0, pulse)))
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(x + 3, cy), 3, 3)
            x += 6 + GAP
        elif chip.kind == update_flow.CHIP_CHECKING:
            ring = QRectF(x + 1, cy - 4.5, 9, 9)
            track = QColor(ink)
            track.setAlphaF(0.25)
            p.setPen(QPen(track, 2.0))
            p.drawEllipse(ring)
            pen = QPen(QColor("#ffffff") if self._dark else QColor("#333333"), 2.0)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            angle = 0.0 if motion.is_reduced() else (elapsed % 800.0) / 800.0 * 360.0
            p.drawArc(ring, int((90 - angle) * 16), int(-90 * 16))
            x += 11 + GAP
        elif chip.kind == update_flow.CHIP_UP_TO_DATE:
            paint.draw_icon(p, "check", QRectF(x, cy - 6, 12, 12), ink)
            x += 12 + GAP
        font = fonts.ui(11, 700)
        label_w = paint.text_width(chip.label, font)
        paint.draw_text_line(p, chip.label, font, ink,
                             QRectF(x, rect.y(), label_w + 2, rect.height()))
        if chip.kind == update_flow.CHIP_DOWNLOADING and chip.percent >= 0:
            mono = fonts.mono(11, 700)
            paint.draw_text_line(
                p, f"{chip.percent}%", mono, ink,
                QRectF(x + label_w + GAP, rect.y(),
                       paint.text_width("100%", mono) + 2, rect.height()))
        if self.hasFocus() and self._keyboard_focus:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#ffffff") if self._dark else QColor("#222222"), 2.0))
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), HEIGHT / 2 + 3, HEIGHT / 2 + 3)
        p.end()
        if not self._enter.active() and chip.kind not in (
                update_flow.CHIP_UPDATE, update_flow.CHIP_CHECKING):
            self._ticker.stop()
