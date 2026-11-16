"""The counters under a toon's portrait and name: jellybeans on hand, in the
bank, Cartoonival tokens while they apply, and the lock that keeps the
counters showing. Laff is not here: the game's own meter is on screen.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

from utils.strips import glyphs, paint, tokens
from utils.strips.tokens import tr

HOVER_GAP = 4.0     # between the strip and the counters; part of the hover area
SIDE = 8.0          # room for the lock's halo
GLYPH = 14.0
GLYPH_GAP = 4.0
CELL_GAP = 10.0
LOCK = 18.0
LOCK_PULL = 3.0
FONT_PX = 12.0
UNKNOWN = "–"


@dataclass(frozen=True)
class CountersModel:
    beans: int | None = None
    bank: int | None = None
    tokens: int | None = None      # None: no token cell at all
    locked: bool = False
    accent: str = "#4a8fe7"
    name: str = ""                 # shown first when the strip's name plate is collapsed


def _number(value: int | None) -> str:
    return UNKNOWN if value is None else f"{int(value):,}"


class CountersView(QWidget):
    lock_clicked = Signal()
    hover_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = CountersModel()
        self._style = tokens.NEON_STYLE
        self._scale = 1.0
        self._lock_hover = False
        self._pressed = False
        self._parts: list = []
        self._pill = QRectF()
        self._lock = QRectF()
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self._relayout()

    # -- inputs -------------------------------------------------------------

    def model(self) -> CountersModel:
        return self._model

    def set_model(self, model: CountersModel) -> None:
        if model != self._model:
            self._model = model
            self._relayout()

    def set_style(self, name: str) -> None:
        style = tokens.style_for(name)
        if style is not self._style:
            self._style = style
            self._relayout()

    def set_scale(self, scale: float) -> None:
        scale = float(scale) if scale and scale > 0 else 1.0
        if abs(scale - self._scale) > 1e-6:
            self._scale = scale
            self._relayout()

    # -- geometry (design px, origin at the widget's top-left) --------------

    def _font(self, bold_name: bool = False):
        f = paint.strip_font(FONT_PX, 700)
        try:
            from PySide6.QtGui import QFont
            f.setFeature(QFont.Tag("tnum"), 1)      # tabular numerals
        except Exception:
            pass
        return f

    def _relayout(self) -> None:
        m, neon = self._model, self._style.is_neon
        fm = QFontMetricsF(self._font())
        pad_l, pad_r, pad_v, border = (10.0, 4.0, 3.0, 1.0) if neon else (0.0, 0.0, 0.0, 0.0)
        height = LOCK + 2 * (pad_v + border)
        top = HOVER_GAP
        mid = top + height / 2.0
        x = SIDE + border + pad_l
        parts = []
        if m.name:
            w = fm.horizontalAdvance(m.name)
            parts.append(("name", QRectF(x, top, w, height), m.name))
            x += w + CELL_GAP
        cells = [("bean", m.beans), ("jar", m.bank)]
        if m.tokens is not None:
            cells.append(("token", m.tokens))
        for kind, value in cells:
            text = _number(value)
            parts.append((kind, QRectF(x, mid - GLYPH / 2.0, GLYPH, GLYPH), ""))
            x += GLYPH + GLYPH_GAP
            w = fm.horizontalAdvance(text)
            parts.append(("text", QRectF(x, top, w, height), text))
            x += w + CELL_GAP
        x -= LOCK_PULL
        self._lock = QRectF(x, mid - LOCK / 2.0, LOCK, LOCK)
        x += LOCK + pad_r + border
        self._pill = QRectF(SIDE, top, x - SIDE, height)
        self._parts = parts
        self._design = QSize(int(round(x + SIDE)), int(round(top + height + SIDE)))
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self) -> QSize:
        k = self._scale
        return QSize(int(round(self._design.width() * k)),
                     int(round(self._design.height() * k)))

    def _to_widget(self, r: QRectF) -> QRectF:
        k = self._scale
        return QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k)

    def lock_rect(self) -> QRectF:
        return self._to_widget(self._lock)

    def pill_rect(self) -> QRectF:
        return self._to_widget(self._pill)

    def shape_region(self):
        """The pill, for a window shape. In the Flat look the counters are
        bare text, which needs something behind it to be a shape at all."""
        return paint.path_region(
            paint.rounded(self._pill, self._pill.height() / 2.0), self._scale)

    def set_backed(self, backed: bool) -> None:
        """Paint a solid pill behind bare text (no compositor)."""
        if bool(backed) != getattr(self, "_backed", False):
            self._backed = bool(backed)
            self.update()

    def input_rects(self) -> list[QRect]:
        """The counters and the gap above them: the pointer can travel from
        the name down to the lock without leaving."""
        area = QRectF(self._pill.x(), 0.0, self._pill.width(),
                      self._pill.bottom())
        return [self._to_widget(area).toAlignedRect()]

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.render_counters(p)
        p.end()

    def render_counters(self, p: QPainter) -> None:
        m, neon = self._model, self._style.is_neon
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(self._scale, self._scale)
        lock = self._lock.translated(0.0, 1.0 if self._pressed else 0.0)
        if neon:
            radius = self._pill.height() / 2.0
            if m.locked:
                paint.paint_glow(p, lock, LOCK / 2.0, tr(m.accent, 50), 6.0)
            p.fillPath(paint.rounded(self._pill, radius), tokens.rgba(0, 0, 0, 0.6))
            paint._border(p, paint.rounded, self._pill, radius, 1.0,
                          tokens.rgba(255, 255, 255, 0.16))
        elif getattr(self, "_backed", False):
            p.fillPath(paint.rounded(self._pill, self._pill.height() / 2.0),
                       QColor(tokens.POPOVER_BASE))
        font = self._font()
        white = QColor("#ffffff")
        flags = Qt.AlignLeft | Qt.AlignVCenter
        for kind, rect, text in self._parts:
            if kind == "bean":
                glyphs.paint_bean(p, rect)
            elif kind == "jar":
                glyphs.paint_jar(p, rect)
            elif kind == "token":
                glyphs.paint_token(p, rect)
            else:
                if not neon:
                    # 0 1px 3px rgba(0,0,0,.95), 0 0 1px rgba(0,0,0,.9)
                    shade = tokens.rgba(0, 0, 0, 0.3)
                    for dx, dy in ((0, 1), (-1, 1), (1, 1), (0, 0), (0, 2),
                                   (-1, 0), (1, 0), (0, -1)):
                        paint._text(p, rect.translated(dx, dy), text, font, shade, flags)
                paint._text(p, rect, text, font, white, flags)
        # The lock.
        if neon:
            fill = QColor(m.accent) if m.locked else tokens.rgba(255, 255, 255, 0.08)
            ink = white if m.locked else tokens.rgba(255, 255, 255, 0.6)
            shape = paint.rounded(lock, LOCK / 2.0)
        else:
            fill = QColor(m.accent) if m.locked else tokens.rgba(0, 0, 0, 0.55)
            ink = white if m.locked else tokens.rgba(255, 255, 255, 0.75)
            shape = paint.rounded(lock, 4.0)
        p.fillPath(shape, fill)
        if self._lock_hover:
            p.fillPath(shape, paint.HOVER_VEIL)
        glyphs.paint_padlock(p, glyphs.centred_square(lock, 11.0), ink,
                             is_open=not m.locked)
        p.restore()

    # -- pointer ------------------------------------------------------------

    def _on_lock(self, pos) -> bool:
        return self.lock_rect().contains(pos)

    def enterEvent(self, event) -> None:
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._lock_hover = False
        self._pressed = False
        self.hover_changed.emit(False)
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        over = self._on_lock(event.position())
        if over != self._lock_hover:
            self._lock_hover = over
            self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._on_lock(event.position()):
            self._pressed = True
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        was, self._pressed = self._pressed, False
        self.update()
        if was and event.button() == Qt.LeftButton and self._on_lock(event.position()):
            self.lock_clicked.emit()

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            if self._on_lock(event.pos()):
                QToolTip.showText(event.globalPos(), self.lock_tooltip(), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def lock_tooltip(self) -> str:
        return ("Unlock: show on hover only" if self._model.locked
                else "Lock: keep counters shown")
