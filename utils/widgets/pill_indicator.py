"""PillIndicator — paint-based 'you are here' chip-rail pill.

Animates by interpolating its painted rect (a QRectF in parent coordinates),
NOT by moving/resizing a widget. Zero layout reflow per frame.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, QRectF, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

import utils.motion as motion


class PillIndicator(QWidget):
    """Overlay widget sized to its parent (the chip rail). Paints a single
    rounded-rect pill at self._pill_rect.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._pill_rect = QRectF()
        self._anim: Optional[QVariantAnimation] = None
        self._top_color = QColor("#7c5cff")
        self._bottom_color = QColor("#5a3fd6")
        self._radius = 8.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Match parent geometry; caller is responsible for resizing on
        # parent resize events.
        if parent is not None:
            self.resize(parent.size())

    def set_colors(self, top_hex: str, bottom_hex: str) -> None:
        self._top_color = QColor(top_hex)
        self._bottom_color = QColor(bottom_hex)
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

    def paintEvent(self, event) -> None:
        if self._pill_rect.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        grad = QLinearGradient(
            0, self._pill_rect.top(),
            0, self._pill_rect.bottom(),
        )
        grad.setColorAt(0.0, self._top_color)
        grad.setColorAt(1.0, self._bottom_color)
        p.setBrush(grad)
        p.drawRoundedRect(self._pill_rect, self._radius, self._radius)
