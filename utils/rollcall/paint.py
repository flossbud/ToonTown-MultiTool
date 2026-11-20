"""Painting the stage's fixed parts: the blue background, soft shadows, the
toon renders with their drop shadow, icons, and wrapped text.
"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QTextCharFormat, QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene,
)

from utils.rollcall import tokens as T
from utils.rollcall.fonts import asset_path

# ── Blur and shadows ───────────────────────────────────────────────────────


def blur_image(source: QImage, radius: float) -> QImage:
    """``source`` blurred by ``radius`` device px. The caller pads the image:
    nothing is drawn outside it."""
    if radius <= 0:
        return source
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(source))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(source.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    scene.render(painter, QRectF(out.rect()), QRectF(source.rect()))
    painter.end()
    return out


_shadow_cache: dict[tuple, QPixmap] = {}


def box_shadow(width: int, height: int, radius: float, blur: float,
               alpha: float, dpr: float) -> tuple[QPixmap, int]:
    """A rounded box's blurred shadow and the margin it needs on every side.
    Draw it at (x - margin, y - margin + offset_y)."""
    key = (width, height, radius, blur, round(alpha, 3), round(dpr, 3))
    margin = int(math.ceil(blur * 1.25))
    cached = _shadow_cache.get(key)
    if cached is not None:
        return cached, margin
    w = int(round((width + 2 * margin) * dpr))
    h = int(round((height + 2 * margin) * dpr))
    image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(dpr, dpr)
    painter.setPen(Qt.NoPen)
    painter.setBrush(T.rgba(0, 0, 0, alpha))
    painter.drawRoundedRect(QRectF(margin, margin, width, height), radius, radius)
    painter.end()
    image = blur_image(image, blur * dpr)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    if len(_shadow_cache) > 12:
        _shadow_cache.clear()
    _shadow_cache[key] = pixmap
    return pixmap, margin


# ── The stage background ───────────────────────────────────────────────────

_bg_cache: dict[tuple, QPixmap] = {}


def stage_background(size: QSize, dpr: float) -> QPixmap:
    """Solid blue, the dot pattern, then light and shade. Square-cornered:
    the caller clips it to the window's radius."""
    key = (size.width(), size.height(), round(dpr, 3))
    cached = _bg_cache.get(key)
    if cached is not None:
        return cached
    w, h = size.width(), size.height()
    pixmap = QPixmap(int(round(w * dpr)), int(round(h * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(T.STAGE_BLUE)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)

    # Dots: 2 px radius, soft to 2.6, on a 24 px grid, and the same grid
    # offset by 12 on both axes.
    dot = QRadialGradient(QPointF(0, 0), 2.6)
    dot.setColorAt(0.0, T.white(0.10))
    dot.setColorAt(2.0 / 2.6, T.white(0.10))
    dot.setColorAt(1.0, T.white(0.0))
    for offset in (12, 0):
        y = offset
        while y <= h + 3:
            x = offset
            while x <= w + 3:
                p.save()
                p.translate(x, y)
                p.setBrush(QBrush(dot))
                p.drawEllipse(QPointF(0, 0), 2.6, 2.6)
                p.restore()
                x += 24
            y += 24

    # Shade: dark on the left, where the copy sits.
    r, g, b = T.STAGE_SHADE
    shade = QLinearGradient(0, 0, w, 0)
    shade.setColorAt(0.0, T.rgba(r, g, b, 0.95))
    shade.setColorAt(0.52, T.rgba(r, g, b, 0.60))
    shade.setColorAt(1.0, T.rgba(r, g, b, 0.20))
    p.fillRect(QRectF(0, 0, w, h), QBrush(shade))

    # Light: an ellipse 460 x 320 centred at 70 % / 0 %, gone by 70 %.
    r, g, b = T.STAGE_GLOW
    glow = QRadialGradient(QPointF(0, 0), 1.0)
    glow.setColorAt(0.0, T.rgba(r, g, b, 0.30))
    glow.setColorAt(0.70, T.rgba(r, g, b, 0.0))
    glow.setColorAt(1.0, T.rgba(r, g, b, 0.0))
    p.save()
    p.translate(w * 0.70, 0)
    p.scale(460, 320)
    p.setBrush(QBrush(glow))
    p.drawRect(QRectF(-1, -1, 2, 2))
    p.restore()
    p.end()
    if len(_bg_cache) > 8:
        _bg_cache.clear()
    _bg_cache[key] = pixmap
    return pixmap


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# ── Toons ──────────────────────────────────────────────────────────────────

TOON_PAD = 28          # logical px of room around a toon for its drop shadow
_toon_sources: dict[str, QImage] = {}
_toon_cache: dict[tuple, QPixmap] = {}


def _toon_source(index: int, pose: str) -> QImage:
    name = f"toon{index}-{pose}.png"
    image = _toon_sources.get(name)
    if image is None:
        image = QImage(asset_path(os.path.join("rollcall", name)))
        if not image.isNull():
            image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        _toon_sources[name] = image
    return image


def toon_pixmap(index: int, pose: str, size: int, dpr: float) -> QPixmap:
    """Toon ``index`` (1-4) fitted in a ``size`` square with its drop shadow
    (0 12px 12px, black 42 %), padded by TOON_PAD on every side. Null if the
    render is missing."""
    key = (index, pose, size, round(dpr, 3))
    cached = _toon_cache.get(key)
    if cached is not None:
        return cached
    source = _toon_source(index, pose)
    if source.isNull():
        _toon_cache[key] = QPixmap()
        return _toon_cache[key]
    side = int(round(size * dpr))
    pad = int(round(TOON_PAD * dpr))
    toon = source.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    full = QSize(side + 2 * pad, side + 2 * pad)
    ox = pad + (side - toon.width()) // 2
    oy = pad + (side - toon.height())            # contain, standing on the bottom edge

    shadow = QImage(full, QImage.Format_ARGB32_Premultiplied)
    shadow.fill(Qt.transparent)
    p = QPainter(shadow)
    p.drawImage(ox, oy + int(round(12 * dpr)), toon)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(shadow.rect(), T.rgba(0, 0, 0, 0.42))
    p.end()
    shadow = blur_image(shadow, 12 * dpr)

    out = QImage(full, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawImage(0, 0, shadow)
    p.drawImage(ox, oy, toon)
    p.end()
    pixmap = QPixmap.fromImage(out)
    pixmap.setDevicePixelRatio(dpr)
    if len(_toon_cache) > 40:
        _toon_cache.clear()
    _toon_cache[key] = pixmap
    return pixmap


_mark_cache: dict[tuple, QPixmap] = {}


def wordmark(height: int, dpr: float) -> QPixmap:
    """The wordmark image at ``height`` logical px. Never typeset."""
    key = (height, round(dpr, 3))
    cached = _mark_cache.get(key)
    if cached is not None:
        return cached
    source = QImage(asset_path(os.path.join("logos", "ttmt_logo_textonly.png")))
    if source.isNull():
        pixmap = QPixmap()
    else:
        scaled = source.scaledToHeight(int(round(height * dpr)), Qt.SmoothTransformation)
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(dpr)
    _mark_cache[key] = pixmap
    return pixmap


# ── Icons (24-unit stroke icons, 2 px stroke, round caps and joins) ────────


def _icon_path(name: str) -> QPainterPath:
    path = QPainterPath()
    if name == "check":
        path.moveTo(20, 6)
        path.lineTo(9, 17)
        path.lineTo(4, 12)
    elif name == "play":
        path.moveTo(6, 3)
        path.lineTo(20, 12)
        path.lineTo(6, 21)
        path.closeSubpath()
    elif name == "down":
        path.moveTo(21, 15)
        path.lineTo(21, 19)
        path.quadTo(21, 21, 19, 21)
        path.lineTo(5, 21)
        path.quadTo(3, 21, 3, 19)
        path.lineTo(3, 15)
        path.moveTo(7, 10)
        path.lineTo(12, 15)
        path.lineTo(17, 10)
        path.moveTo(12, 15)
        path.lineTo(12, 3)
    elif name == "ext":
        path.moveTo(15, 3)
        path.lineTo(21, 3)
        path.lineTo(21, 9)
        path.moveTo(10, 14)
        path.lineTo(21, 3)
        path.moveTo(18, 13)
        path.lineTo(18, 19)
        path.quadTo(18, 21, 16, 21)
        path.lineTo(5, 21)
        path.quadTo(3, 21, 3, 19)
        path.lineTo(3, 8)
        path.quadTo(3, 6, 5, 6)
        path.lineTo(11, 6)
    return path


def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Stroke icon ``name`` (check, play, down, ext) into ``rect``."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 24.0, rect.height() / 24.0)
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(_icon_path(name))
    p.restore()


# ── Text ───────────────────────────────────────────────────────────────────


class TextBlock:
    """Wrapped text with a fixed line height, laid out once and drawn many
    times. ``runs`` mixes fonts and colours in one paragraph: a list of
    (text, font or None, colour or None)."""

    def __init__(self, text: str | list, font: QFont, color: QColor, width: float,
                 line_height: float, *, balance: bool = False, single_line: bool = False,
                 shadow: QColor | None = None, shadow_dy: float = 0.0):
        if isinstance(text, str):
            runs = [(text, None, None)]
        else:
            runs = list(text)
        self.text = "".join(r[0] for r in runs)
        self.font = font
        self.color = color
        self.line_height = float(line_height)
        self.shadow = shadow
        self.shadow_dy = shadow_dy
        self._runs = runs
        self._layout = QTextLayout(self.text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.NoWrap if single_line
                           else QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._layout.setTextOption(option)
        formats = []
        position = 0
        for run_text, run_font, run_color in runs:
            if run_font is not None or run_color is not None:
                fmt = QTextCharFormat()
                if run_font is not None:
                    fmt.setFont(run_font)
                if run_color is not None:
                    fmt.setForeground(QBrush(run_color))
                frange = QTextLayout.FormatRange()
                frange.start = position
                frange.length = len(run_text)
                frange.format = fmt
                formats.append(frange)
            position += len(run_text)
        if formats:
            self._layout.setFormats(formats)
        wrap = 100000.0 if single_line else max(1.0, float(width))
        if balance and not single_line:
            wrap = self._balanced_width(wrap)
        self.lines = self._break(wrap)
        self.width = max((self._layout.lineAt(i).naturalTextWidth()
                          for i in range(self.lines)), default=0.0)
        self.height = self.lines * self.line_height

    def _break(self, width: float) -> int:
        layout = self._layout
        layout.beginLayout()
        count = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            # Each line box is line_height tall with the glyphs centred in it
            # (CSS half-leading).
            line.setPosition(QPointF(0, count * self.line_height
                                     + (self.line_height - line.height()) / 2.0))
            count += 1
        layout.endLayout()
        return count

    def _balanced_width(self, width: float) -> float:
        """The narrowest width that keeps the line count: lines of similar
        length instead of one long line and an orphan (text-wrap: balance)."""
        lines = self._break(width)
        if lines <= 1:
            return width
        low, high = width / lines * 0.6, width
        for _ in range(12):
            mid = (low + high) / 2.0
            if self._break(mid) <= lines:
                high = mid
            else:
                low = mid
        return math.ceil(high)

    def draw(self, p: QPainter, x: float, y: float, opacity: float = 1.0) -> None:
        if opacity <= 0.0 or not self.text:
            return
        p.save()
        p.setOpacity(p.opacity() * opacity)
        if self.shadow is not None:
            p.setPen(self.shadow)
            self._draw_plain(p, x, y + self.shadow_dy)
        p.setPen(self.color)
        self._layout.draw(p, QPointF(x, y))
        p.restore()

    def _draw_plain(self, p: QPainter, x: float, y: float) -> None:
        """The same glyphs in the painter's pen colour, ignoring run colours
        (the headline's hard shadow)."""
        p.setFont(self.font)
        for i in range(self._layout.lineCount()):
            line = self._layout.lineAt(i)
            line.draw(p, QPointF(x, y))


def text_width(text: str, font: QFont) -> float:
    return QFontMetricsF(font).horizontalAdvance(text)


def elide(text: str, font: QFont, width: float) -> str:
    return QFontMetricsF(font).elidedText(text, Qt.ElideRight, int(width))


def draw_text_line(p: QPainter, text: str, font: QFont, color: QColor,
                   rect: QRectF, align=Qt.AlignLeft | Qt.AlignVCenter) -> None:
    p.setFont(font)
    p.setPen(color)
    flags = getattr(align, "value", align) | Qt.TextSingleLine.value
    p.drawText(rect, int(flags), text)
