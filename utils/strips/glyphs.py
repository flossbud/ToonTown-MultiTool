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


# -- counter glyphs (their own colours; the square only sets the size) ------

def paint_bean(p: QPainter, rect: QRectF) -> None:
    """Jellybeans on hand: one open curve stroked twice with round caps (dark
    under, pink over) and a highlight dot."""
    _begin(p, rect)
    p.save()
    p.translate(12.0, 12.0)
    p.rotate(-10.0)
    p.translate(-12.0, -12.0)
    path = QPainterPath(QPointF(14.2, 6.6))
    path.cubicTo(6.4, 9.4, 6.4, 15.4, 12.2, 18.2)
    p.setBrush(Qt.NoBrush)
    for colour, width in (("#b03064", 11.0), ("#ff6fae", 8.8)):
        p.setPen(_stroke(QColor(colour), width))
        p.drawPath(path)
    p.restore()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffd4e6"))
    p.drawEllipse(QPointF(12.3, 7.2), 1.5, 1.5)
    p.restore()


def paint_jar(p: QPainter, rect: QRectF) -> None:
    """Jellybeans in the bank: a glass jar of candy with a red lid."""
    _begin(p, rect)
    body = QPainterPath(QPointF(7.8, 6.6))
    body.lineTo(16.2, 6.6)
    body.cubicTo(16.2, 8.7, 19.8, 9.6, 19.8, 14.0)
    body.cubicTo(19.8, 18.4, 16.5, 21.4, 12.0, 21.4)
    body.cubicTo(7.5, 21.4, 4.2, 18.4, 4.2, 14.0)
    body.cubicTo(4.2, 9.6, 7.8, 8.7, 7.8, 6.6)
    body.closeSubpath()
    pen = QPen(QColor("#a9dced"), 1.3)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    glass = QColor(214, 241, 250)
    glass.setAlphaF(0.4)
    p.setBrush(glass)
    p.drawPath(body)
    p.setPen(Qt.NoPen)
    for x, y, r, colour in ((8.9, 15.6, 1.7, "#ff6fae"), (12.3, 17.4, 1.7, "#57c96a"),
                            (15.5, 15.3, 1.7, "#f2b431"), (11.6, 13.2, 1.6, "#6cc4ef")):
        p.setBrush(QColor(colour))
        p.drawEllipse(QPointF(x, y), r, r)
    p.setPen(QPen(QColor("#a32a24"), 1.2))
    p.setBrush(QColor("#e0453c"))
    p.drawRoundedRect(QRectF(4.6, 2.1, 14.8, 5.1), 1.9, 1.9)
    p.restore()


def paint_token(p: QPainter, rect: QRectF) -> None:
    """Cartoonival tokens: a gold party popper and three bits of confetti."""
    _begin(p, rect)
    gold = QColor("#f0b429")
    cone = QPainterPath(QPointF(2.9, 21.1))
    cone.lineTo(8.8, 6.2)
    cone.lineTo(17.7, 15.1)
    cone.closeSubpath()
    pen = QPen(QColor("#b9821b"), 1.2)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(gold)
    p.drawPath(cone)
    p.setPen(Qt.NoPen)
    for x, y, r in ((19.6, 5.4, 1.8), (14.4, 3.2, 1.1), (21.3, 10.8, 1.1)):
        p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def paint_padlock(p: QPainter, rect: QRectF, color, is_open: bool) -> None:
    """Solid body; the shackle closed, or lifted clear on the right."""
    _begin(p, rect)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(4.0, 11.0, 16.0, 10.0), 2.0, 2.0)
    p.setPen(_stroke(color, 2.6))
    p.setBrush(Qt.NoBrush)
    ring = QRectF(8.0, 3.0, 8.0, 8.0)
    shackle = QPainterPath(QPointF(8.0, 11.0))
    shackle.lineTo(8.0, 7.0)
    if is_open:
        shackle.arcTo(ring, 180.0, -150.0)     # ends near (15.5, 5)
    else:
        shackle.arcTo(ring, 180.0, -180.0)
        shackle.lineTo(16.0, 11.0)
    p.drawPath(shackle)
    p.restore()


def paint_close(p: QPainter, rect: QRectF, color) -> None:
    _begin(p, rect)
    p.setPen(_stroke(color, 2.6))
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))
    p.restore()
