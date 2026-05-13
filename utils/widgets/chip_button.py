"""ChipButton — a QToolButton that scales as a uniform unit on hover/press.

Animating only `iconSize` looks juddery because the icon shrinks but the
text and chip frame stay fixed. ChipButton instead renders itself with a
`paint_scale` factor (QTransform.scale around its center in paintEvent),
so the icon, text, background, and border all scale together.

Hover and press states are managed internally; the rest of the app just
constructs a ChipButton like a QToolButton.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, Property, QPropertyAnimation, Qt, QTimer,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QToolButton

import utils.motion as motion


class ChipButton(QToolButton):
    """QToolButton with an animatable `paint_scale` property and built-in
    hover/press state machine.

    Scale composition:
        - default      → NORMAL_SCALE (1.00)
        - hover        → HOVER_SCALE  (1.06)
        - press        → PRESS_SCALE  (0.88)
        - hover + press → PRESS_SCALE (press wins)

    paint_scale > 1.0 may clip at the widget's bounds by 1-2 px on chips
    with no extra contentsMargins; the chip's QSS padding gives enough
    breathing room that this is below perception for the 1.06 target.
    """

    NORMAL_SCALE = 1.0
    HOVER_SCALE = 1.06
    PRESS_SCALE = 0.88
    DURATION_PRESS_MS = 130
    DURATION_HOVER_MS = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paint_scale = 1.0
        self._is_hovered = False
        self._is_pressed = False
        self._taking_snapshot = False
        self._scale_anim: Optional[QPropertyAnimation] = None
        # Hook our own signals; QToolButton's pressed/released fire whenever
        # the mouse engages the button (or the keyboard activates it via
        # space/enter), which is exactly the cue we want for press feedback.
        self.pressed.connect(lambda: self._set_pressed(True))
        self.released.connect(lambda: self._set_pressed(False))

    # ── paint_scale Qt property ──────────────────────────────────────────
    def _get_paint_scale(self) -> float:
        return self._paint_scale

    def _set_paint_scale(self, value: float) -> None:
        self._paint_scale = float(value)
        self.update()

    paint_scale = Property(float, _get_paint_scale, _set_paint_scale)

    # ── State machine ────────────────────────────────────────────────────
    def _set_hovered(self, value: bool) -> None:
        if self._is_hovered == value:
            return
        self._is_hovered = value
        self._reanimate_to_target()

    def _set_pressed(self, value: bool) -> None:
        if self._is_pressed == value:
            return
        self._is_pressed = value
        self._reanimate_to_target()

    def _target_scale(self) -> float:
        if self._is_pressed:
            return self.PRESS_SCALE
        if self._is_hovered:
            return self.HOVER_SCALE
        return self.NORMAL_SCALE

    def _reanimate_to_target(self) -> None:
        target = self._target_scale()
        # Press transitions use the faster timing; non-press use hover timing.
        duration_ms = (
            self.DURATION_PRESS_MS if self._is_pressed else self.DURATION_HOVER_MS
        )
        self._animate_to(target, duration_ms)

    def _animate_to(self, target: float, duration_ms: int) -> None:
        if motion.is_reduced():
            self._set_paint_scale(target)
            return
        if (
            self._scale_anim is not None
            and self._scale_anim.state() == QAbstractAnimation.Running
        ):
            self._scale_anim.stop()
        raw = duration_ms * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))
        anim = QPropertyAnimation(self, b"paint_scale")
        anim.setDuration(duration)
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(self._paint_scale)
        anim.setEndValue(target)
        anim.finished.connect(lambda t=target: self._set_paint_scale(t))
        self._scale_anim = anim
        # Deferred start so zero-duration animations complete synchronously
        # and so callers can connect to finished before it fires (matches
        # the pattern used elsewhere in the motion module).
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        timer.start(0)

    # ── Mouse hover ──────────────────────────────────────────────────────
    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)

    # ── Paint: scale the entire chip via QPainter.scale ─────────────────
    def paintEvent(self, event) -> None:
        if self._paint_scale == 1.0 or self._taking_snapshot:
            super().paintEvent(event)
            return
        # Capture the chip's normal (unscaled) appearance via a guarded grab.
        # grab() calls render() which calls paintEvent — the _taking_snapshot
        # flag routes that recursive call to super().paintEvent (1.0 path)
        # so we get a clean unscaled snapshot.
        self._taking_snapshot = True
        try:
            snapshot = self.grab()
        finally:
            self._taking_snapshot = False
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.translate(cx, cy)
        p.scale(self._paint_scale, self._paint_scale)
        p.translate(-cx, -cy)
        p.drawPixmap(0, 0, snapshot)
