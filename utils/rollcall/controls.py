"""The stage's controls: buttons, the text link, the switch, the checkbox and
the window's two traffic lights. Each paints itself and keeps FOCUS_PAD of
room around its visible shape for the keyboard focus ring (2 px white, 2 px
off the edge), so ``visual_rect`` is what layouts align.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from utils.rollcall import fonts, motion, paint
from utils.rollcall import tokens as T

PAD = T.FOCUS_PAD


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class _Control(QAbstractButton):
    """Shared behaviour: hover tween, keyboard-only focus ring, a fade the
    copy column drives while it enters."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._fade = 1.0
        self._hover = motion.Tween(0.0)
        self._keyboard_focus = False
        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)

    # The copy column fades its controls with its text.
    def set_fade(self, alpha: float) -> None:
        alpha = max(0.0, min(1.0, alpha))
        if alpha != self._fade:
            self._fade = alpha
            self.update()

    def visual_rect(self) -> QRectF:
        return QRectF(PAD, PAD, self.width() - 2 * PAD, self.height() - 2 * PAD)

    def _animating(self) -> bool:
        return self._hover.active()

    def _kick(self) -> None:
        if not self._ticker.isActive():
            self._ticker.start()
        self.update()

    def _on_tick(self) -> None:
        if not self._animating():
            self._ticker.stop()
        self.update()

    def enterEvent(self, event) -> None:
        self._hover.to(1.0, T.PRESS_MS)
        self._kick()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0, T.PRESS_MS)
        self._kick()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = event.reason() in (
            Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        self._keyboard_focus = False
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)

    def _focus_ring(self, p: QPainter, rect: QRectF, radius: float) -> None:
        if not (self.hasFocus() and self._keyboard_focus):
            return
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#ffffff"), 2.0))
        p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        p.restore()


class RcButton(_Control):
    """A stage button. ``kind``: gold (the one primary action per screen),
    ghost, red, neutral, warn. ``icon`` leads the label; ``trail`` follows it."""

    def __init__(self, text: str, kind: str = "ghost", *, height: int = 44,
                 px: int = 13, pad: int = 14, icon: str = "", trail: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self._label = text
        self._height = height
        self._px = px
        self._pad = pad
        self._icon = icon
        self._trail = trail
        self.setText(text)
        self.setAccessibleName(text)
        self.setFixedSize(self.sizeHint())

    @classmethod
    def gold(cls, text: str, variant: T.Variant, icon: str = "", parent=None) -> "RcButton":
        return cls(text, "gold", height=variant.gold_h, px=variant.gold_px,
                   pad=variant.gold_pad, icon=icon, parent=parent)

    @classmethod
    def ghost(cls, text: str, variant: T.Variant, trail: str = "", parent=None) -> "RcButton":
        return cls(text, "ghost", height=variant.gold_h, px=variant.ghost_px,
                   pad=variant.ghost_pad, trail=trail, parent=parent)

    @classmethod
    def red(cls, text: str, parent=None) -> "RcButton":
        return cls(text, "red", height=44, px=13, pad=20, parent=parent)

    @classmethod
    def neutral(cls, text: str, small: bool = False, parent=None) -> "RcButton":
        if small:
            return cls(text, "neutral", height=28, px=11, pad=10, parent=parent)
        return cls(text, "neutral", height=34, px=13, pad=14, parent=parent)

    @classmethod
    def warn(cls, text: str, parent=None) -> "RcButton":
        return cls(text, "warn", height=28, px=11, pad=10, parent=parent)

    def set_label(self, text: str) -> None:
        if text != self._label:
            self._label = text
            self.setText(text)
            self.setAccessibleName(text)
            self.setFixedSize(self.sizeHint())
            self.update()

    def _font(self):
        if self.kind == "gold":
            return fonts.ui(self._px, 800, spacing=0.06 * self._px)
        return fonts.ui(self._px, 600)

    def _shown_text(self) -> str:
        return self._label.upper() if self.kind == "gold" else self._label

    def _content_width(self) -> float:
        width = paint.text_width(self._shown_text(), self._font())
        if self.kind == "gold":
            width -= 0.06 * self._px          # no tracking after the last letter
        if self._icon:
            width += 16 + 7
        if self._trail:
            width += 12 + 7
        return width

    def sizeHint(self) -> QSize:
        width = self._content_width() + 2 * self._pad
        return QSize(int(width + 0.999) + 2 * PAD, self._height + 2 * PAD)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._fade)
        rect = self.visual_rect()
        down = self.isDown()
        if down:
            rect.translate(0, 1)
        hover = self._hover.value() if self.isEnabled() else 0.0
        kind = self.kind
        if kind == "gold":
            bg, border, ink = _mix(T.GOLD, T.GOLD_B, hover), T.GOLD_B, T.GOLD_INK
            if not down:
                # The hard 3 px ledge under the primary button.
                p.setPen(Qt.NoPen)
                p.setBrush(T.rgba(0, 0, 0, 0.28))
                p.drawRoundedRect(rect.translated(0, 3), 8, 8)
        elif kind == "red":
            bg, border, ink = _mix(T.RED, T.RED_HOVER, hover), T.RED_B, QColor("#ffffff")
        elif kind == "neutral":
            bg, border, ink = _mix(T.BTN_BG, T.BTN_HOVER, hover), T.BTN_BORDER, QColor("#ffffff")
        elif kind == "warn":
            bg = _mix(T.rgba(255, 149, 0, 0.16), T.rgba(255, 149, 0, 0.26), hover)
            border, ink = T.KEEP_ALIVE_B, T.WARN_BTN_TEXT
        else:
            bg = _mix(T.rgba(0, 0, 0, 0.26), T.rgba(0, 0, 0, 0.44), hover)
            border, ink = T.white(0.24), T.white(0.90)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, 8, 8)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 7.5, 7.5)

        font = self._font()
        text = self._shown_text()
        x = rect.x() + (rect.width() - self._content_width()) / 2.0
        if self._icon:
            paint.draw_icon(p, self._icon, QRectF(x, rect.center().y() - 8, 16, 16), ink)
            x += 16 + 7
        text_w = paint.text_width(text, font)
        paint.draw_text_line(p, text, font, ink,
                             QRectF(x, rect.y(), text_w + 2, rect.height()))
        if self._trail:
            tx = x + text_w - (0.06 * self._px if kind == "gold" else 0) + 7
            paint.draw_icon(p, self._trail, QRectF(tx, rect.center().y() - 6, 12, 12), ink)
        self._focus_ring(p, self.visual_rect(), 8)
        p.end()


class RcLink(_Control):
    """A quiet text link under the actions: Inter 11 / 500, white 66 %;
    white and underlined on hover."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._label = text
        self.setText(text)
        self.setAccessibleName(text)
        self.setFixedSize(self.sizeHint())

    def _font(self):
        return fonts.ui(11, 500)

    def sizeHint(self) -> QSize:
        width = paint.text_width(self._label, self._font())
        return QSize(int(width + 1.999) + 2 * PAD, 14 + 2 * PAD)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._fade)
        rect = self.visual_rect()
        hover = self._hover.value()
        color = _mix(T.white(0.66), T.white(1.0), hover)
        font = self._font()
        if self.underMouse():
            font.setUnderline(True)
        paint.draw_text_line(p, self._label, font, color, rect)
        self._focus_ring(p, rect, 3)
        p.end()


class RcSwitch(_Control):
    """34 x 20 switch. Green when on; the Keep-Alive one is orange."""

    def __init__(self, on: bool = False, *, keep_alive: bool = False,
                 name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._on = bool(on)
        self._keep_alive = keep_alive
        self._knob = motion.Tween(1.0 if on else 0.0)
        self.setAccessibleName(name)
        self.setFixedSize(34 + 2 * PAD, 20 + 2 * PAD)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool, animate: bool = True) -> None:
        on = bool(on)
        if on == self._on:
            return
        self._on = on
        if animate and not motion.is_reduced():
            self._knob.to(1.0 if on else 0.0, T.KNOB_MS, T.EASE_KNOB)
            self._kick()
        else:
            self._knob.snap(1.0 if on else 0.0)
            self.update()

    def _animating(self) -> bool:
        return self._hover.active() or self._knob.active()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._fade)
        rect = self.visual_rect()
        k = self._knob.value()
        on_color = T.KEEP_ALIVE if self._keep_alive else T.GREEN
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(T.BTN_BORDER, on_color, k))
        p.drawRoundedRect(rect, 10, 10)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(rect.x() + 2 + 8 + 14 * k, rect.center().y()), 8, 8)
        self._focus_ring(p, rect, 10)
        p.end()


class RcCheckbox(_Control):
    """An 18 px box, a label that may wrap, and a path on its own line."""

    toggled_by_user = Signal(bool)

    def __init__(self, label: str, path: str = "", width: int = 300,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self._label_block = paint.TextBlock(
            label, fonts.ui(12, 400), T.white(0.88), width - 18 - 9, 12 * 1.35)
        self._path = path
        self._tick = motion.Tween(0.0)
        self.setAccessibleName(label)
        height = self._label_block.height + (3 + 13 if path else 0)
        self.setFixedSize(width + 2 * PAD, int(max(18, height) + 0.999) + 2 * PAD)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, checked: bool) -> None:
        self._tick.to(1.0 if checked else 0.0, T.PRESS_MS)
        self._kick()
        self.toggled_by_user.emit(checked)

    def _animating(self) -> bool:
        return self._hover.active() or self._tick.active()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._fade)
        rect = self.visual_rect()
        t = self._tick.value() if self._tick.active() else (1.0 if self.isChecked() else 0.0)
        box = QRectF(rect.x(), rect.y(), 18, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(T.rgba(0, 0, 0, 0.30), T.BLUE, t))
        p.drawRoundedRect(box, 5, 5)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_mix(T.white(0.40), T.BLUE_B, t), 1.0))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4.5, 4.5)
        if t > 0.01:
            p.setOpacity(self._fade * t)
            paint.draw_icon(p, "check", QRectF(box.x() + 3, box.y() + 3, 12, 12),
                            QColor("#ffffff"))
            p.setOpacity(self._fade)
        self._label_block.draw(p, rect.x() + 27, rect.y())
        if self._path:
            paint.draw_text_line(
                p, self._path, fonts.mono(10, 500), T.white(0.60),
                QRectF(rect.x() + 27, rect.y() + self._label_block.height + 3,
                       rect.width() - 27, 13))
        self._focus_ring(p, box, 5)
        p.end()


class Lights(QWidget):
    """Minimize and close, as in the app: 16 px dots in 22 px hit areas, 8 px
    apart. The glyphs show while the pointer is over the cluster."""

    minimize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(2 * T.LIGHT_HIT + T.LIGHT_GAP, T.LIGHT_HIT)
        self._over = -1
        self._inside = False
        self._pressed = -1

    def _index_at(self, pos) -> int:
        if 0 <= pos.x() < T.LIGHT_HIT:
            return 0
        if T.LIGHT_HIT + T.LIGHT_GAP <= pos.x() < self.width():
            return 1
        return -1

    def enterEvent(self, event) -> None:
        self._inside = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._inside = False
        self._over = -1
        self.update()

    def mouseMoveEvent(self, event) -> None:
        over = self._index_at(event.position())
        if over != self._over:
            self._over = over
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = self._index_at(event.position())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        index = self._index_at(event.position())
        pressed, self._pressed = self._pressed, -1
        if index != pressed:
            return
        if index == 0:
            self.minimize_clicked.emit()
        elif index == 1:
            self.close_clicked.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        specs = ((T.TRAFFIC_MIN, T.TRAFFIC_MIN_GLYPH, "min"),
                 (T.TRAFFIC_CLOSE, T.TRAFFIC_CLOSE_GLYPH, "close"))
        for i, (color, glyph, kind) in enumerate(specs):
            cx = T.LIGHT_HIT / 2 + i * (T.LIGHT_HIT + T.LIGHT_GAP)
            cy = T.LIGHT_HIT / 2
            radius = T.LIGHT_DOT / 2 * (1.1 if self._over == i else 1.0)
            p.setPen(Qt.NoPen)
            p.setBrush(color.lighter(118) if self._over == i else color)
            p.drawEllipse(QPointF(cx, cy), radius, radius)
            if self._inside:
                pen = QPen(glyph, 1.6)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                if kind == "min":
                    p.drawLine(QPointF(cx - 3.2, cy), QPointF(cx + 3.2, cy))
                else:
                    p.drawLine(QPointF(cx - 2.8, cy - 2.8), QPointF(cx + 2.8, cy + 2.8))
                    p.drawLine(QPointF(cx - 2.8, cy + 2.8), QPointF(cx + 2.8, cy - 2.8))
        p.end()
