"""GlassDock - the app's tab switcher as one liquid-glass segmented control.

Custom-painted (no QGraphicsEffect, per the v2 kit law): a translucent glass
container holds four segments. A single identity-tinted glass pill slides
between segments on selection and morphs its color from the source tab's
identity color to the destination's as it travels (blue -> red -> gold ->
green); each segment's label brightens by how much the pill covers it. The pill
and hover are painted, not child widgets, so there is zero layout reflow per
frame.
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


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_rect(a: QRectF, b: QRectF, t: float) -> QRectF:
    return QRectF(_lerp(a.x(), b.x(), t), _lerp(a.y(), b.y(), t),
                  _lerp(a.width(), b.width(), t), _lerp(a.height(), b.height(), t))


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(_lerp(a.red(), b.red(), t)),
                  round(_lerp(a.green(), b.green(), t)),
                  round(_lerp(a.blue(), b.blue(), t)))


@dataclass
class _Segment:
    label: str
    icon_maker: str
    accent_key: str
    rect: QRect = field(default_factory=QRect)   # in widget coords


class GlassDock(QWidget):
    selected = Signal(int)   # emitted only on user interaction

    def __init__(self, items, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._selected = 0
        self._deselected = False   # chip-less route: no pill painted
        self._hover = -1
        self._anim: Optional[QVariantAnimation] = None
        self.segments = [_Segment(lbl, mk, key) for (lbl, mk, key) in items]
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._label_font = QFont()
        self._label_font.setPixelSize(13)
        self._compute_layout()
        # The selection pill starts on segment 0.
        pair0 = V2_NAV[self.segments[0].accent_key]
        self._pill_rect = QRectF(self.segments[0].rect)
        self._pill_c = QColor(pair0["c"])
        self._pill_b = QColor(pair0["b"])

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
        return -1 if self._deselected else self._selected

    def select(self, index: int, animate: bool = True) -> None:
        """Slide the selection pill to `index`. Does NOT emit `selected`
        (programmatic). The pill morphs its color from the current tab's
        identity color to the destination's over the slide.

        `index < 0` is the chip-less route: clear the selection entirely.
        No pill or glow paints and every segment renders in its idle color
        until a valid index is selected again (an instant reappear)."""
        if index < 0:
            if not self._deselected:
                self._deselected = True
                self.update()
            return
        was_deselected = self._deselected
        self._deselected = False
        if index == self._selected and not was_deselected:
            return
        self._selected = index
        dest = self.segments[index]
        pair = V2_NAV[dest.accent_key]
        to_rect = QRectF(dest.rect)
        to_c = QColor(pair["c"])
        to_b = QColor(pair["b"])
        # From a deselected state the pill instantly reappears at the target
        # (a slide-from-nowhere would look wrong); is_reduced() also snaps.
        if not animate or motion.is_reduced() or was_deselected:
            self._pill_rect = to_rect
            self._pill_c = to_c
            self._pill_b = to_b
            self.update()
            return
        self._start_slide(to_rect, to_c, to_b)

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
                # A click restores selection even from the deselected route,
                # and even onto the previously-remembered segment.
                if i != self._selected or self._deselected:
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
        if self._deselected:
            # Chip-less route is keyboard-inert: arrow-nav from a deselected
            # dock would re-light from a stale index.
            super().keyPressEvent(e)
            return
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

    # -- slide animation -------------------------------------------------
    def _start_slide(self, to_rect: QRectF, to_c: QColor, to_b: QColor) -> None:
        if self._anim is not None:
            self._anim.stop()
        from_rect = QRectF(self._pill_rect)
        from_c = QColor(self._pill_c)
        from_b = QColor(self._pill_b)
        anim = QVariantAnimation(self)
        raw = motion.DURATION_PILL * motion._TEST_DURATION_SCALE
        anim.setDuration(0 if raw == 0.0 else max(1, int(raw)))
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def on_val(v):
            t = float(v)
            self._pill_rect = _lerp_rect(from_rect, to_rect, t)
            self._pill_c = _lerp_color(from_c, to_c, t)
            self._pill_b = _lerp_color(from_b, to_b, t)
            self.update()

        anim.valueChanged.connect(on_val)
        anim.finished.connect(lambda: on_val(1.0))
        self._anim = anim
        anim.start()

    # -- paint -----------------------------------------------------------
    def _coverage(self, seg: _Segment) -> float:
        """How much of `seg` the selection pill horizontally covers, 0..1."""
        if self._deselected:
            return 0.0
        seg_l, seg_r = seg.rect.x(), seg.rect.x() + seg.rect.width()
        pill_l = self._pill_rect.x()
        pill_r = self._pill_rect.x() + self._pill_rect.width()
        overlap = min(seg_r, pill_r) - max(seg_l, pill_l)
        if overlap <= 0:
            return 0.0
        return min(1.0, overlap / seg.rect.width())

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

        # Selection pill (one moving, color-morphing glass capsule). Skipped
        # entirely on the chip-less route, where nothing is selected.
        if not self._deselected:
            self._paint_selection_pill(p)

        # Idle hover tint + per-segment icon/label (coverage-lit).
        for i, seg in enumerate(self.segments):
            self._paint_segment_content(p, seg, i, t)
        p.end()

    def _paint_selection_pill(self, p: QPainter) -> None:
        r = self._pill_rect
        radius = r.height() / 2
        # Painted glow: concentric strokes in the current (morphing) tint.
        glow = QColor(self._pill_c)
        for w, a in ((10, 0.06), (6, 0.14), (3, 0.22)):
            glow.setAlphaF(a)
            p.setPen(QPen(glow, w))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, radius, radius)
        # Fill + inner ring.
        p.setPen(QPen(with_alpha(self._pill_b, 0.6), 1))
        p.setBrush(with_alpha(self._pill_c, 0.55))
        p.drawRoundedRect(r, radius, radius)

    def _paint_segment_content(self, p: QPainter, seg: _Segment, i: int, t: dict) -> None:
        r = QRectF(seg.rect)
        radius = r.height() / 2
        cov = self._coverage(seg)

        # Hover tint on a mostly-uncovered idle segment.
        if i == self._hover and cov < 0.5:
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor_from_rgba(t["nav_hover"]))
            p.drawRoundedRect(r, radius, radius)

        # Text/icon color lerps idle -> white by pill coverage.
        idle = _qcolor_from_rgba(t["nav_idle_text"])
        text_col = _lerp_color(idle, QColor("#ffffff"), cov)
        maker = getattr(icon_factory, seg.icon_maker)
        icon = maker(ICON, text_col)
        iy = int(r.center().y() - ICON / 2)
        p.drawPixmap(int(r.x() + PAD_X), iy, icon.pixmap(ICON, ICON))
        f_font = QFont(self._label_font)
        f_font.setWeight(QFont.Bold if cov >= 0.5 else QFont.Medium)
        p.setFont(f_font)
        p.setPen(text_col)
        p.drawText(r.adjusted(PAD_X + ICON + ICON_GAP, 0, -PAD_X, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, seg.label)
