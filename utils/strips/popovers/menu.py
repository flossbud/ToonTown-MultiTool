"""A pill menu: a caret pointing up at its anchor, then a centred stack of
outlined pills. Used for a keyset's right-click, the + block's hidden sets
and the toon menu."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils.strips import paint, tokens
from utils.strips.tokens import dk, tr

MARGIN = 10.0        # halo room around the pills
CARET_W = 10.0
CARET_H = 6.0
CARET_TO_PILL = 3.0
PILL_GAP = 4.0
PAD_X = 12.0
PAD_Y = 4.0
BORDER = 2.0
FONT_PX = 11.0
CHECK_W = 9.0
CHECK_GAP = 3.0
ANCHOR_GAP = 5.0     # between the anchor block and the caret's tip


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    disabled: bool = False
    checked: bool = False


class PillMenu(QWidget):
    chosen = Signal(str)

    def __init__(self, items, colour: str, style_name: str = tokens.NEON,
                 scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = tuple(items)
        self._colour = colour
        self._style = tokens.style_for(style_name)
        self._scale = float(scale) if scale and scale > 0 else 1.0
        self._caret_x: float | None = None     # design px from the left edge
        self._flipped = False
        self._hover = -1
        self._pressed = -1
        self._pills: list[QRectF] = []
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self._relayout()

    def items(self) -> tuple:
        return self._items

    def _font(self):
        return paint.strip_font(FONT_PX, 700)

    def _relayout(self) -> None:
        fm = QFontMetricsF(self._font())
        height = FONT_PX + 2 * (PAD_Y + BORDER)
        widths = []
        for it in self._items:
            w = fm.horizontalAdvance(it.label) + 2 * (PAD_X + BORDER)
            if it.checked:
                w += CHECK_W + CHECK_GAP
            widths.append(w)
        widest = max(widths) if widths else 0.0
        full = max(widest, CARET_W) + 2 * MARGIN
        # Dropped below its anchor the caret is on top; flipped above it,
        # the stack is mirrored and the caret hangs underneath.
        y = MARGIN if self._flipped else CARET_H + CARET_TO_PILL
        self._pills = []
        for w in widths:
            self._pills.append(QRectF((full - w) / 2.0, y, w, height))
            y += height + PILL_GAP
        stack = y - PILL_GAP
        self._design = QSize(int(round(full)), int(round(
            stack + (CARET_TO_PILL + CARET_H if self._flipped else MARGIN))))
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self) -> QSize:
        k = self._scale
        return QSize(int(round(self._design.width() * k)),
                     int(round(self._design.height() * k)))

    def set_caret_x(self, widget_x: float) -> None:
        """Where the caret points, in widget px (the anchor's centre)."""
        self._caret_x = widget_x / self._scale
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        """Opened above its anchor (no room below): the caret points down."""
        if bool(flipped) != self._flipped:
            self._flipped = bool(flipped)
            self._relayout()

    def pill_rect(self, index: int) -> QRectF:
        r, k = self._pills[index], self._scale
        return QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k)

    def input_rects(self) -> list[QRect]:
        return [self.pill_rect(i).toAlignedRect() for i in range(len(self._pills))]

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.render_menu(p)
        p.end()

    def render_menu(self, p: QPainter) -> None:
        c, neon = self._colour, self._style.is_neon
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(self._scale, self._scale)
        cx = self._caret_x if self._caret_x is not None else self._design.width() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c))
        if self._flipped:
            tip = float(self._design.height())
            p.drawPolygon(QPolygonF([QPointF(cx, tip),
                                     QPointF(cx + CARET_W / 2.0, tip - CARET_H),
                                     QPointF(cx - CARET_W / 2.0, tip - CARET_H)]))
        else:
            p.drawPolygon(QPolygonF([QPointF(cx, 0.0),
                                     QPointF(cx + CARET_W / 2.0, CARET_H),
                                     QPointF(cx - CARET_W / 2.0, CARET_H)]))
        font = self._font()
        for i, (item, rect) in enumerate(zip(self._items, self._pills)):
            p.save()
            if item.disabled:
                p.setOpacity(0.45)
            if i == self._pressed and not item.disabled:
                rect = rect.translated(0.0, 1.0)
            radius = rect.height() / 2.0
            hot = i == self._hover and not item.disabled
            if neon:
                paint.paint_glow(p, rect, radius, tr(c, 42), 7.0)
                if hot:
                    fill = QBrush(QColor(dk(c, 45)))
                else:
                    fill = QBrush(tokens.body_gradient(rect, c))
            else:
                fill = QBrush(QColor(dk(c, 40) if hot else tokens.POPOVER_BASE))
            p.fillPath(paint.rounded(rect, radius), fill)
            paint._border(p, paint.rounded, rect, radius, BORDER, QColor(c))
            text = rect.adjusted(BORDER + PAD_X, 0, -(BORDER + PAD_X), 0)
            if item.checked:
                mark = QRectF(text.left(), rect.center().y() - CHECK_W / 2.0,
                              CHECK_W, CHECK_W)
                pen = QPen(QColor("#ffffff"), 1.8)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                tick = QPainterPath(QPointF(mark.left() + 0.8, mark.center().y() + 0.4))
                tick.lineTo(mark.left() + 3.4, mark.bottom() - 1.4)
                tick.lineTo(mark.right() - 0.6, mark.top() + 1.4)
                p.setBrush(Qt.NoBrush)
                p.drawPath(tick)
                text.setLeft(text.left() + CHECK_W + CHECK_GAP)
            paint._text(p, text, item.label, font, QColor("#ffffff"),
                        Qt.AlignLeft | Qt.AlignVCenter)
            p.restore()
        p.restore()

    # -- pointer ------------------------------------------------------------

    def _index_at(self, pos) -> int:
        for i in range(len(self._pills)):
            if self.pill_rect(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event) -> None:
        i = self._index_at(event.position())
        if i != self._hover:
            self._hover = i
            live = i >= 0 and not self._items[i].disabled
            self.setCursor(Qt.PointingHandCursor if live else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover = self._pressed = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = self._index_at(event.position())
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, -1
        self.update()
        if event.button() != Qt.LeftButton:
            return
        i = self._index_at(event.position())
        if i >= 0 and i == pressed and not self._items[i].disabled:
            self.chosen.emit(self._items[i].key)
