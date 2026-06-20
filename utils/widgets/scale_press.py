# utils/widgets/scale_press.py
"""ScalePushButton — a QPushButton that animates a "pushed-in" shrink on press.

Mirrors utils/widgets/chip_button.ChipButton's scale machinery for QPushButtons,
PRESS-ONLY (hover feedback is left to QSS :hover). On press the whole button
(fill, border, icon) animates to PRESS_SCALE about its center and springs back on
release, repainting through a center-scaled QStylePainter so the QSS-driven
background, border, and icon scale together. Only the PAINT scales — the widget
rect never changes, so layout is unaffected. Reduced-motion aware.

Driven by the button's own pressed/released signals, so a subclass that overrides
mouse events (e.g. KeepAliveBtn's rapid-fire hold) composes with it for free.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, Property, QPropertyAnimation, QTimer,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QPushButton, QStyle, QStyleOptionButton, QStylePainter,
)

import utils.motion as motion


class ScalePushButton(QPushButton):
    PRESS_SCALE = 0.90
    DURATION_PRESS_MS = 130

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paint_scale = 1.0
        self._is_pressed = False
        self._scale_anim: Optional[QPropertyAnimation] = None
        self.pressed.connect(lambda: self._set_pressed(True))
        self.released.connect(lambda: self._set_pressed(False))

    # ── paint_scale Qt property ──────────────────────────────────────────
    def _get_paint_scale(self) -> float:
        return self._paint_scale

    def _set_paint_scale(self, value: float) -> None:
        self._paint_scale = float(value)
        self.update()

    paint_scale = Property(float, _get_paint_scale, _set_paint_scale)

    # ── Press state -> animation ─────────────────────────────────────────
    def _set_pressed(self, value: bool) -> None:
        if self._is_pressed == value:
            return
        self._is_pressed = value
        self._animate_to(self.PRESS_SCALE if value else 1.0)

    def _animate_to(self, target: float) -> None:
        if motion.is_reduced():
            self._set_paint_scale(target)
            return
        if (
            self._scale_anim is not None
            and self._scale_anim.state() == QAbstractAnimation.Running
        ):
            self._scale_anim.stop()
        raw = self.DURATION_PRESS_MS * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))
        anim = QPropertyAnimation(self, b"paint_scale")
        anim.setDuration(duration)
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(self._paint_scale)
        anim.setEndValue(target)
        anim.finished.connect(lambda t=target: self._set_paint_scale(t))
        self._scale_anim = anim
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        timer.start(0)

    # ── Scaled paint helpers (reusable by custom-painted subclasses) ─────
    def _begin_scaled_paint(self) -> QStylePainter:
        """A QStylePainter on this widget, center-scaled by paint_scale, AA on."""
        p = QStylePainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.translate(cx, cy)
        p.scale(self._paint_scale, self._paint_scale)
        p.translate(-cx, -cy)
        return p

    def _draw_button_chrome(self, painter: QStylePainter) -> None:
        """Draw the QSS-styled button (bg, border, text, icon) through *painter*
        (already center-scaled by the caller)."""
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter.drawControl(QStyle.CE_PushButton, option)

    def paintEvent(self, event) -> None:
        if self._paint_scale == 1.0:
            super().paintEvent(event)
            return
        p = self._begin_scaled_paint()
        self._draw_button_chrome(p)
