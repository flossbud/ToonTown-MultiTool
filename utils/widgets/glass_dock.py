"""GlassDock - the app's tab switcher as one liquid-glass segmented control.

Custom-painted (no QGraphicsEffect, per the v2 kit law): a translucent glass
container holds four segments; the selected segment cross-fades an identity
tint + inner ring + painted glow. Selection state and hover are painted, not
child widgets, so there is zero layout reflow per frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

import utils.icon_factory as icon_factory
import utils.motion as motion
from utils.color_math import with_alpha
from utils.theme_manager import V2_NAV, get_v2_tokens
from utils.widgets.portrait_badge import _qcolor_from_rgba


SEG_H = 36
PAD_X = 16
ICON = 16
ICON_GAP = 7
CPAD = 3          # container padding around the segment row
SEG_GAP = 2       # gap between segments
GLOW = 8          # painted-glow margin reserved around the container


@dataclass
class _Segment:
    label: str
    icon_maker: str
    accent_key: str
    rect: QRect = field(default_factory=QRect)   # in widget coords
    fade: float = 0.0                            # 0..1 selected-tint amount


class GlassDock(QWidget):
    selected = Signal(int)   # emitted only on user interaction

    def __init__(self, items, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._selected = 0
        self._hover = -1
        self._anim: Optional[QVariantAnimation] = None
        self.segments = [_Segment(lbl, mk, key) for (lbl, mk, key) in items]
        self.segments[0].fade = 1.0
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._label_font = QFont()
        self._label_font.setPixelSize(13)
        self._compute_layout()

    # -- geometry --------------------------------------------------------
    def _seg_width(self, seg: _Segment) -> int:
        self._label_font.setWeight(QFont.Bold)
        adv = QFontMetrics(self._label_font).horizontalAdvance(seg.label)
        return 2 * PAD_X + ICON + ICON_GAP + adv

    def _compute_layout(self) -> None:
        x = GLOW + CPAD
        y = GLOW + CPAD
        for seg in self.segments:
            w = self._seg_width(seg)
            seg.rect = QRect(x, y, w, SEG_H)
            x += w + SEG_GAP
        # total inner width = sum widths + gaps; strip the trailing gap
        self._inner_w = x - SEG_GAP - (GLOW + CPAD)
        self._pill_w = self._inner_w + 2 * CPAD
        self._pill_h = SEG_H + 2 * CPAD

    def sizeHint(self) -> QSize:
        return QSize(self._pill_w + 2 * GLOW, self._pill_h + 2 * GLOW)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # -- public API ------------------------------------------------------
    def selected_index(self) -> int:
        return self._selected

    def select(self, index: int, animate: bool = True) -> None:
        """Set the active segment. Does NOT emit `selected` (programmatic)."""
        if index == self._selected:
            return
        self._selected = index
        if not animate or motion.is_reduced():
            for i, seg in enumerate(self.segments):
                seg.fade = 1.0 if i == index else 0.0
            self.update()
            return
        self._start_fade(index)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    # -- interaction -----------------------------------------------------
    def _segment_at(self, pos) -> int:
        for i, seg in enumerate(self.segments):
            if seg.rect.contains(pos):
                return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = self._segment_at(e.position().toPoint())
            if i >= 0:
                if i != self._selected:
                    self.select(i)
                self.selected.emit(i)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        i = self._segment_at(e.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Left, Qt.Key_Up):
            self._activate_via_key((self._selected - 1) % len(self.segments))
        elif e.key() in (Qt.Key_Right, Qt.Key_Down):
            self._activate_via_key((self._selected + 1) % len(self.segments))
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.selected.emit(self._selected)
        else:
            super().keyPressEvent(e)

    def _activate_via_key(self, index: int) -> None:
        self.select(index)
        self.selected.emit(index)

    # -- cross-fade ------------------------------------------------------
    def _start_fade(self, index: int) -> None:
        if self._anim is not None:
            self._anim.stop()
        start = [seg.fade for seg in self.segments]
        target = [1.0 if i == index else 0.0 for i in range(len(self.segments))]
        anim = QVariantAnimation(self)
        raw = motion.DURATION_HOVER * motion._TEST_DURATION_SCALE
        anim.setDuration(0 if raw == 0.0 else max(1, int(raw)))
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def on_val(v):
            for i, seg in enumerate(self.segments):
                seg.fade = start[i] + (target[i] - start[i]) * float(v)
            self.update()

        anim.valueChanged.connect(on_val)
        anim.finished.connect(lambda: on_val(1.0))
        self._anim = anim
        anim.start()

    # -- paint -----------------------------------------------------------
    def paintEvent(self, e):
        t = get_v2_tokens(self._is_dark)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Container glass (translucent, composited over the opaque band).
        neutral = "#ffffff" if self._is_dark else "#0f172a"
        pill = QRectF(GLOW, GLOW, self._pill_w, self._pill_h)
        radius = pill.height() / 2
        p.setPen(QPen(with_alpha(neutral, 0.11), 1))
        p.setBrush(with_alpha(neutral, 0.055))
        p.drawRoundedRect(pill, radius, radius)

        for i, seg in enumerate(self.segments):
            self._paint_segment(p, seg, i, t)
        p.end()

    def _paint_segment(self, p: QPainter, seg: _Segment, i: int, t: dict) -> None:
        r = QRectF(seg.rect)
        radius = r.height() / 2
        pair = V2_NAV[seg.accent_key]
        f = seg.fade

        # Painted glow (only when tinted). Concentric strokes, alpha scaled by f.
        if f > 0.01:
            glow = QColor(pair["c"])
            for w, a in ((10, 0.06), (6, 0.14), (3, 0.22)):
                glow.setAlphaF(a * f)
                p.setPen(QPen(glow, w))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, radius, radius)

        # Base fill: idle hover tint, then the identity tint fading in on top.
        if i == self._hover and f < 0.5:
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor_from_rgba(t["nav_hover"]))
            p.drawRoundedRect(r, radius, radius)
        if f > 0.01:
            p.setPen(QPen(with_alpha(pair["b"], 0.6 * f), 1))
            p.setBrush(with_alpha(pair["c"], 0.55 * f))
            p.drawRoundedRect(r, radius, radius)

        # Icon + label. Text color lerps idle -> white by f.
        idle = _qcolor_from_rgba(t["nav_idle_text"])
        white = QColor("#ffffff")
        text_col = QColor(
            round(idle.red() + (white.red() - idle.red()) * f),
            round(idle.green() + (white.green() - idle.green()) * f),
            round(idle.blue() + (white.blue() - idle.blue()) * f),
        )
        maker = getattr(icon_factory, seg.icon_maker)
        icon = maker(ICON, text_col)
        iy = int(r.center().y() - ICON / 2)
        p.drawPixmap(int(r.x() + PAD_X), iy, icon.pixmap(ICON, ICON))
        f_font = QFont(self._label_font)
        f_font.setWeight(QFont.Bold if i == self._selected else QFont.Medium)
        p.setFont(f_font)
        p.setPen(text_col)
        p.drawText(r.adjusted(PAD_X + ICON + ICON_GAP, 0, -PAD_X, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, seg.label)
