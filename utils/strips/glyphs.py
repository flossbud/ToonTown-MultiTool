"""The strip's glyphs, drawn from the handoff's 24-unit paths.

Each painter takes the square the glyph occupies and one colour; strokes
scale with the square, so a glyph is the same shape at any size.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

_BOX = 24.0


def _begin(p: QPainter, rect: QRectF) -> float:
    """Map the 24-unit glyph box onto `rect`; returns the unit scale."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(rect.x(), rect.y())
    k = min(rect.width(), rect.height()) / _BOX
    p.scale(k, k)
    return k


def _stroke(color: QColor, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def paint_power(p: QPainter, rect: QRectF, color) -> None:
    """Open ring with a stem: 270 degrees of a radius-9 circle centred on
    (12, 13), the gap at the top."""
    _begin(p, rect)
    p.setPen(_stroke(color, 2.6))
    p.setBrush(Qt.NoBrush)
    ring = QRectF(3.0, 4.0, 18.0, 18.0)
    path = QPainterPath()
    path.arcMoveTo(ring, 45.0)
    path.arcTo(ring, 45.0, -270.0)
    p.drawPath(path)
    p.drawLine(QPointF(12.0, 2.0), QPointF(12.0, 12.0))
    p.restore()


def paint_mouse(p: QPainter, rect: QRectF, color) -> None:
    _begin(p, rect)
    p.setPen(_stroke(color, 2.4))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(6.0, 3.0, 12.0, 18.0), 6.0, 6.0)
    p.drawLine(QPointF(12.0, 7.0), QPointF(12.0, 11.0))
    p.restore()


_BOLT = ((13, 2), (3, 14), (11, 14), (10, 22), (21, 9), (13, 9))


def paint_bolt(p: QPainter, rect: QRectF, color) -> None:
    _begin(p, rect)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in _BOLT]))
    p.restore()


def paint_plus(p: QPainter, rect: QRectF, color) -> None:
    _begin(p, rect)
    p.setPen(_stroke(color, 3.0))
    p.drawLine(QPointF(12.0, 5.0), QPointF(12.0, 19.0))
    p.drawLine(QPointF(5.0, 12.0), QPointF(19.0, 12.0))
    p.restore()


def centred_square(block: QRectF, size: float) -> QRectF:
    """A `size` square centred in `block`."""
    return QRectF(block.center().x() - size / 2.0,
                  block.center().y() - size / 2.0, size, size)
