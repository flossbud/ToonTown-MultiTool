"""Paint helpers for _PoseTile loading/failure visual states.

Widget-agnostic - accepts a QPainter and a QRect; the caller owns
the painter lifetime and any additional clip setup.

Functions:
  paint_shimmer(painter, rect, phase)  - animated sweep highlight for loading state
  paint_failed_mark(painter, rect)     - static X mark for failed state
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


def paint_shimmer(painter: QPainter, rect: QRect, phase: float) -> None:
    """Paint a sweeping shimmer highlight clipped to the ellipse bounded by *rect*.

    *phase* is 0.0..1.0 and controls the highlight's horizontal position.
    At phase 0.0 the highlight is at the left edge; at 1.0 it is at the
    right edge. The caller should cycle phase to animate.
    """
    painter.save()

    # Clip paint to the circle so the highlight never bleeds outside.
    clip = QPainterPath()
    clip.addEllipse(rect)
    painter.setClipPath(clip)

    # Sweeping linear gradient - center moves from left to right as phase increases.
    w = float(rect.width())
    band_half = w * 0.35
    cx = rect.left() + w * phase
    cy = float(rect.center().y())

    grad = QLinearGradient(QPointF(cx - band_half, cy), QPointF(cx + band_half, cy))
    grad.setColorAt(0.0, QColor(255, 255, 255, 0))
    grad.setColorAt(0.5, QColor(255, 255, 255, 48))
    grad.setColorAt(1.0, QColor(255, 255, 255, 0))

    painter.setPen(Qt.NoPen)
    painter.setBrush(grad)
    painter.drawRect(rect)

    painter.restore()


def paint_failed_mark(painter: QPainter, rect: QRect) -> None:
    """Paint a static X mark inside the ellipse bounded by *rect*.

    Draws two diagonal lines in a muted red, indicating a load failure.
    """
    painter.save()

    # Inset the X relative to the circle so it sits comfortably inside.
    inset = max(rect.width() // 4, 6)
    inner = rect.adjusted(inset, inset, -inset, -inset)

    pen = QPen(QColor(210, 70, 70, 200))
    pen.setWidthF(2.5)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    tl = QPointF(inner.topLeft())
    tr = QPointF(inner.topRight())
    bl = QPointF(inner.bottomLeft())
    br = QPointF(inner.bottomRight())
    painter.drawLine(tl, br)
    painter.drawLine(tr, bl)

    painter.restore()
