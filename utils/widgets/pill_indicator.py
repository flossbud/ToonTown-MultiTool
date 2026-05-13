"""PillIndicator — paint-based 'you are here' chip-rail pill.

Animates by interpolating its painted rect (a QRectF in parent coordinates),
NOT by moving/resizing a widget. Zero layout reflow per frame.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, QRectF, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

import utils.motion as motion


class PillIndicator(QWidget):
    """Overlay widget sized to its parent (the chip rail). Paints a hollow
    rounded-rect border at self._pill_rect — the selected-chip indicator.

    The chips themselves render with a transparent background so the pill's
    border is visible around the selected chip and slides between chips
    on nav change.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._pill_rect = QRectF()
        self._anim: Optional[QVariantAnimation] = None
        self._border_color = QColor("#7c5cff")  # overridden by set_colors
        self._border_width = 2.0
        self._radius = 8.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Match parent geometry; caller is responsible for resizing on
        # parent resize events.
        if parent is not None:
            self.resize(parent.size())

    def set_colors(self, border_hex: str) -> None:
        """Set the pill border color (typically theme accent)."""
        self._border_color = QColor(border_hex)
        self.update()

    def set_pill_rect(self, rect: QRectF) -> None:
        self._pill_rect = QRectF(rect)
        self.update()

    def slide_to(self, target: QRectF) -> Optional[QVariantAnimation]:
        if motion.is_reduced():
            self.set_pill_rect(target)
            return None

        if self._anim is not None and self._anim.state() == QAbstractAnimation.Running:
            self._anim.stop()

        start = QRectF(self._pill_rect) if not self._pill_rect.isEmpty() else target

        anim = QVariantAnimation(self)
        raw = motion.DURATION_PILL * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))
        anim.setDuration(duration)
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(start)
        anim.setEndValue(target)
        # valueChanged drives each frame; finished ensures the end-value is
        # applied even when duration==0 (zero-duration skips valueChanged).
        anim.valueChanged.connect(self.set_pill_rect)
        anim.finished.connect(lambda: self.set_pill_rect(anim.endValue()))
        self._anim = anim
        # Defer start so callers can connect to anim.finished before it fires
        # (zero-duration animations complete synchronously inside start()).
        # Parent the timer to self so it isn't garbage-collected before firing.
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        timer.start(0)
        return anim

    def cancel_animation(self) -> None:
        """Stop any in-flight slide_to animation. No-op if nothing running.

        Callers (the chip rail's resize filter) use this when they need
        to snap the pill to a new geometry — the resize has just shifted
        the chips, so any animation's end value is stale.
        """
        if (
            self._anim is not None
            and self._anim.state() == QAbstractAnimation.Running
        ):
            self._anim.stop()

    def paintEvent(self, event) -> None:
        if self._pill_rect.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._border_color)
        pen.setWidthF(self._border_width)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Inset by half the pen width so the stroke sits exactly on the
        # chip's bounds rather than spilling outward.
        inset = self._border_width / 2.0
        rect = self._pill_rect.adjusted(inset, inset, -inset, -inset)
        p.drawRoundedRect(rect, self._radius, self._radius)
