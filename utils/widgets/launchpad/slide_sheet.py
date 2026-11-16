"""SlideSheetHost: the launchpad window's slide-over sheet (handoff section 2).

An overlay child of any parent widget. It covers the parent below `top`
(the 112 px header) with a scrim (a 5 px blur of what is behind, under
rgba(10,10,10,.55)); click it to close. On the right sits the sheet panel:
664 px wide, full height, bg-app fill, 1 px left border, a 2 px top line in
the sheet's identity colour, and a painted shadow to its left. The panel has
a 56 px header (optional back button, title, sub line, close button) and a
scrolling body padded 14 16 18; content widgets stack their blocks 12 px
apart by laying them out with material.sheet_stack().

Motion: the panel slides in from the right over 320 ms on
cubic-bezier(.22,1,.36,1) and the scrim fades over 220 ms; both are skipped
when motion is reduced (utils.motion, which honours REDUCE_MOTION). Esc
closes. One sheet at a time: open() while open swaps the content in place.

Signals mark state changes, not animation ends: `opened` fires when a sheet
opens (not on a swap), `closed` when close() starts, `content_changed` on
every open or swap.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QToolButton, QVBoxLayout, QWidget, QFrame,
)

import utils.motion as motion
from utils.icon_factory import make_chevron_left_icon, make_x_icon
from utils.shared_widgets import ElidingLabel
from utils.theme_manager import is_dark_palette
from utils.widgets.auto_hide_scrollbar import install_modern_scrollbar
from utils.widgets.backdrop_blur import BackdropBlur
from utils.widgets.launchpad.material import (
    BLOCK_GAP, BUTTON_RADIUS, GLOW_PAD, STACK_SPACING, qcolor, sheet_palette,
    sheet_stack,
)

HEADER_H = 112          # window header the sheet sits under
SHEET_W = 664
SHEET_HEAD_H = 56
TOP_LINE = 2
BODY_MARGINS = (16, 14, 16, 18)   # left, top, right, bottom, to visible edges
SLIDE_MS = 320
SCRIM_MS = 220
SHADOW_OFFSET = 22      # box-shadow: -22px 0 44px rgba(0,0,0,.5)
SHADOW_BLUR = 44
HEAD_BTN = 28


def sheet_easing() -> QEasingCurve:
    """cubic-bezier(.22, 1, .36, 1)."""
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.22, 1.0), QPointF(0.36, 1.0),
                                QPointF(1.0, 1.0))
    return curve


class _Scrim(BackdropBlur):
    """Blurred snapshot + dim over the content area, and the panel's shadow.
    A click anywhere on it asks the host to close."""

    BLUR_RADIUS = 5
    clicked = Signal()

    def __init__(self, host: "SlideSheetHost"):
        super().__init__(host, mouse_transparent=False)
        self._host = host
        self._dim = QColor(10, 10, 10, 140)
        self._shadow = QColor(0, 0, 0, 128)

    def set_colors(self, dim: QColor, shadow: QColor) -> None:
        self._dim = dim
        self._shadow = shadow
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setOpacity(self._opacity)
        if self._blurred is not None and not self._blurred.isNull():
            p.drawPixmap(self.rect(), self._blurred, self._blurred.rect())
        p.fillRect(self.rect(), self._dim)
        p.setOpacity(1.0)
        # The panel's shadow, approximated by a horizontal fade ending at its
        # left edge (the CSS shadow is the panel shifted 22 px left, blurred
        # 44 px). Painted here because the scrim is what lies beside it.
        x = self._host.panel.x()
        if x < self.width():
            span = SHADOW_OFFSET + SHADOW_BLUR
            grad = QLinearGradient(x - span, 0, x, 0)
            edge = QColor(self._shadow)
            edge.setAlphaF(self._shadow.alphaF() * 0.6)
            clear = QColor(self._shadow)
            clear.setAlpha(0)
            grad.setColorAt(0.0, clear)
            grad.setColorAt(1.0, edge)
            p.fillRect(QRectF(x - span, 0, span, self.height()), grad)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        e.accept()


class _HeadButton(QToolButton):
    """28 px header button (back, close): border-card outline, radius 8."""

    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(HEAD_BTN, HEAD_BTN)
        self.setIconSize(QSize(14, 14))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def apply_theme(self, pal: dict) -> None:
        self.setStyleSheet(
            "QToolButton { background: transparent;"
            f" border: 1px solid {pal['border_card']}; border-radius: {BUTTON_RADIUS}px;"
            " padding: 0; }"
            f"QToolButton:hover {{ background: {pal['close_hover']};"
            f" border-color: {pal['border_light']}; }}")


class _SheetHeader(QWidget):
    """56 px row on bg-deep with a 1 px bottom border."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(SHEET_HEAD_H)
        self._bg = QColor("#111111")
        self._rule = QColor("#2e2e2e")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 14, 0)
        lay.setSpacing(10)
        self.back_button = _HeadButton("Back", self)
        self.back_button.hide()
        lay.addWidget(self.back_button)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title_label = ElidingLabel("", parent=self)
        self.sub_label = ElidingLabel("", parent=self)
        col.addStretch(1)
        col.addWidget(self.title_label)
        col.addWidget(self.sub_label)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.close_button = _HeadButton("Close", self)
        lay.addWidget(self.close_button)

    def apply_theme(self, pal: dict) -> None:
        self._bg = qcolor(pal["bg_deep"])
        self._rule = qcolor(pal["border_muted"])
        self.title_label.setStyleSheet(
            f"QLabel {{ font-size: 15px; font-weight: 700; color: {pal['text']};"
            " background: transparent; border: none; }")
        self.sub_label.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {pal['text_muted']};"
            " background: transparent; border: none; }")
        icon_col = qcolor(pal["text_secondary"])
        self.back_button.setIcon(make_chevron_left_icon(14, icon_col))
        self.close_button.setIcon(make_x_icon(14, icon_col))
        self.back_button.apply_theme(pal)
        self.close_button.apply_theme(pal)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        p.fillRect(QRect(0, self.height() - 1, self.width(), 1), self._rule)
        p.end()


class _SheetPanel(QWidget):
    """The sheet itself: fill, left border, identity top line; header + body."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self._fill = QColor("#1a1a1a")
        self._edge = QColor("#363636")
        self._identity = QColor("#0077ff")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, TOP_LINE, 0, 0)
        lay.setSpacing(0)
        self.header = _SheetHeader(self)
        lay.addWidget(self.header)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.body = QWidget()
        self.body.setObjectName("sheet_body")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        self.body.setStyleSheet("QWidget#sheet_body { background: transparent; }")
        self.body_layout = QVBoxLayout(self.body)
        # Blocks carry GLOW_PAD themselves (see material.GLOW_PAD).
        l, t, r, b = (m - GLOW_PAD for m in BODY_MARGINS)
        self.body_layout.setContentsMargins(l, t, r, b)
        self.body_layout.setSpacing(0)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

    def set_identity(self, color: str) -> None:
        self._identity = QColor(color)
        self.update()

    def apply_theme(self, pal: dict) -> None:
        self._fill = qcolor(pal["bg_app"])
        self._edge = qcolor(pal["border_card"])
        self.header.apply_theme(pal)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._fill)
        p.fillRect(QRect(0, 0, 1, self.height()), self._edge)
        p.fillRect(QRect(0, 0, self.width(), TOP_LINE), self._identity)
        p.end()


class SlideSheetHost(QWidget):
    opened = Signal()
    closed = Signal()
    content_changed = Signal(object)     # the content widget, or None

    def __init__(self, parent: QWidget, top: int = HEADER_H,
                 is_dark: bool | None = None):
        super().__init__(parent)
        self._top = int(top)
        self._is_dark = is_dark_palette() if is_dark is None else bool(is_dark)
        self._content: QWidget | None = None
        self._identity = "#0077ff"
        self._back: Callable[[], None] | None = None
        self._open = False
        self._slide = None
        self._fade = None

        self.scrim = _Scrim(self)
        self.scrim.clicked.connect(self.close)
        self.panel = _SheetPanel(self)
        self.panel.header.close_button.clicked.connect(self.close)
        self.panel.header.back_button.clicked.connect(self._on_back)

        self.apply_theme(self._is_dark)
        self.hide()
        parent.installEventFilter(self)
        self._sync_geometry()

    # ── public API ──────────────────────────────────────────────────────
    def is_open(self) -> bool:
        return self._open

    def current_content(self) -> QWidget | None:
        return self._content

    def open(self, content: QWidget, identity: str, title: str,
             sub: str = "") -> None:
        """Show `content` in the sheet. Opening while open swaps the content
        in place (no slide); the previous content is hidden, kept alive and
        left to its owner."""
        self._identity = identity
        self.panel.set_identity(identity)
        self.set_header(title, sub)
        self._set_content(content)
        if self._open:
            self.content_changed.emit(content)
            return
        self._sync_geometry()                 # panel parked off to the right
        self._open = True
        self._capture_backdrop()
        self.show()
        self.raise_()
        self.panel.setFocus(Qt.OtherFocusReason)
        self._animate(opening=True)
        self.opened.emit()
        self.content_changed.emit(content)

    def set_header(self, title: str, sub: str = "") -> None:
        self.panel.header.title_label.setText(title or "")
        self.panel.header.sub_label.setText(sub or "")
        self.panel.header.sub_label.setVisible(bool(sub))

    def set_back(self, callback: Callable[[], None] | None) -> None:
        """Show the back button and call `callback` on click; None hides it."""
        self._back = callback
        self.panel.header.back_button.setVisible(callback is not None)

    def close(self) -> bool:  # noqa: A003 (QWidget.close is replaced on purpose)
        """Slide the sheet out. Returns False if nothing was open."""
        if not self._open:
            return False
        self._open = False
        self._animate(opening=False)
        self.closed.emit()
        return True

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = bool(is_dark)
        pal = sheet_palette(self._is_dark)
        self.scrim.set_colors(qcolor(pal["scrim"]), qcolor(pal["shadow"]))
        self.panel.apply_theme(pal)
        bar = getattr(self.panel.scroll, "_auto_hide_scrollbar", None)
        if bar is None:
            install_modern_scrollbar(self.panel.scroll, is_dark=self._is_dark)
        else:
            bar.set_theme(self._is_dark)
        if self._content is not None and hasattr(self._content, "apply_theme"):
            self._content.apply_theme(self._is_dark)

    # ── internals ───────────────────────────────────────────────────────
    def _set_content(self, content: QWidget) -> None:
        if content is self._content:
            return
        lay = self.panel.body_layout
        if self._content is not None:
            lay.removeWidget(self._content)
            self._content.hide()
            self._content.setParent(self)      # kept alive, hidden
        self._content = content
        lay.insertWidget(lay.count() - 1, content)
        content.show()
        if hasattr(content, "apply_theme"):
            content.apply_theme(self._is_dark)
        self.panel.scroll.verticalScrollBar().setValue(0)

    def _on_back(self) -> None:
        if self._back is not None:
            self._back()

    def _content_rect(self) -> QRect:
        p = self.parentWidget()
        return QRect(0, self._top, p.width(), max(0, p.height() - self._top))

    def _sync_geometry(self) -> None:
        self.setGeometry(self._content_rect())
        self.scrim.setGeometry(0, 0, self.width(), self.height())
        self.panel.resize(min(SHEET_W, self.width()), self.height())
        if self._slide is None or self._slide.state() != QVariantAnimation.Running:
            self.panel.move(self._panel_x(1.0 if self._open else 0.0), 0)

    def _panel_x(self, progress: float) -> int:
        """Panel left edge for slide progress 0 (off to the right) .. 1."""
        shown = self.width() - self.panel.width()
        hidden = self.width()
        return round(hidden + (shown - hidden) * progress)

    def _capture_backdrop(self) -> None:
        parent = self.parentWidget()
        rect = self._content_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            self.scrim.set_source_pixmap(None)
            return
        was_visible = self.isVisible()
        if was_visible:
            self.hide()
        try:
            self.scrim.set_source_pixmap(parent.grab(rect))
        finally:
            if was_visible:
                self.show()

    def _animate(self, opening: bool) -> None:
        for anim in (self._slide, self._fade):
            if anim is not None:
                anim.stop()
        start_x = self.panel.x()
        end_x = self._panel_x(1.0 if opening else 0.0)
        start_op = self.scrim.opacity
        end_op = 1.0 if opening else 0.0
        if motion.is_reduced() or not self.isVisible():
            self.panel.move(end_x, 0)
            self.scrim.opacity = end_op
            self._finish(opening)
            return
        slide = QVariantAnimation(self)
        slide.setDuration(SLIDE_MS)
        slide.setEasingCurve(sheet_easing())
        slide.setStartValue(float(start_x))
        slide.setEndValue(float(end_x))
        slide.valueChanged.connect(self._on_slide)
        slide.finished.connect(lambda o=opening: self._finish(o))
        fade = QPropertyAnimation(self.scrim, b"opacity", self)
        fade.setDuration(SCRIM_MS)
        fade.setEasingCurve(sheet_easing())
        fade.setStartValue(float(start_op))
        fade.setEndValue(float(end_op))
        self._slide, self._fade = slide, fade
        slide.start()
        fade.start()

    def _on_slide(self, value) -> None:
        self.panel.move(round(float(value)), 0)
        self.scrim.update()

    def _finish(self, opening: bool) -> None:
        if not opening and not self._open:
            self.hide()
            self.scrim.set_source_pixmap(None)

    # ── events ──────────────────────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape and self._open:
            self.close()
            e.accept()
            return
        super().keyPressEvent(e)
