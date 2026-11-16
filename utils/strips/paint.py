"""Painters for the strip's blocks, one set per look.

Everything is drawn in logical px at scale 1.0; the widget scales the
painter. A `tone` callable maps every colour on its way to the painter: the
identity normally, the dim filter for a disabled toon's Neon blocks.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)

from utils import cc_race_assets
from utils.strips import glyphs, tokens
from utils.strips.tokens import StripStyle, dk, lt, tr

Tone = Callable[[QColor], QColor]


def identity(c: QColor) -> QColor:
    return c


WHITE = QColor("#ffffff")
HOVER_VEIL = tokens.rgba(255, 255, 255, 0.14)


# -- fonts ------------------------------------------------------------------

def strip_font(px: float, weight: int, families=tokens.FONT_FAMILIES) -> QFont:
    """A pixel-sized font. The strip paints its own text, so the app
    stylesheet's point size never applies to it."""
    f = QFont()
    f.setFamilies(list(families))
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(QFont.Weight(int(weight)))
    try:
        # A variable font (Inter ships as one) picks its weight from this
        # axis; a static family ignores it.
        f.setVariableAxis(QFont.Tag("wght"), float(weight))
    except (AttributeError, TypeError):
        pass
    # The painter is scaled to keep the strip true-size on the game window;
    # hinted metrics would not scale with it.
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def name_font(style: StripStyle) -> QFont:
    return strip_font(style.font_name_px, 700)


def measure_name(style: StripStyle, text: str) -> float:
    return QFontMetricsF(name_font(style)).horizontalAdvance(text or "")


# -- shapes -----------------------------------------------------------------

def rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, min(radius, rect.width() / 2.0, rect.height() / 2.0))
    path.addRoundedRect(rect, r, r)
    return path


def right_rounded(rect: QRectF, radius: float) -> QPainterPath:
    """Square on the left, rounded on the right: the name plate."""
    r = max(0.0, min(radius, rect.width() / 2.0, rect.height() / 2.0))
    path = QPainterPath()
    path.moveTo(rect.left(), rect.top())
    path.lineTo(rect.right() - r, rect.top())
    if r > 0:
        path.arcTo(QRectF(rect.right() - 2 * r, rect.top(), 2 * r, 2 * r), 90, -90)
    path.lineTo(rect.right(), rect.bottom() - r)
    if r > 0:
        path.arcTo(QRectF(rect.right() - 2 * r, rect.bottom() - 2 * r, 2 * r, 2 * r), 0, -90)
    path.lineTo(rect.left(), rect.bottom())
    path.closeSubpath()
    return path


def _toned_gradient(g: QLinearGradient, tone: Tone) -> QLinearGradient:
    out = QLinearGradient(g.start(), g.finalStop())
    for pos, colour in g.stops():
        out.setColorAt(pos, tone(colour))
    return out


def _border(p: QPainter, shape: Callable[[QRectF, float], QPainterPath],
            rect: QRectF, radius: float, width: float, colour: QColor,
            dashed: bool = False) -> None:
    """A CSS border: `width` px, entirely inside `rect`."""
    half = width / 2.0
    pen = QPen(colour, width)
    pen.setJoinStyle(Qt.MiterJoin)
    if dashed:
        pen.setCapStyle(Qt.FlatCap)
        pen.setDashPattern([2.0, 2.0])   # in pen widths
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(shape(rect.adjusted(half, half, -half, -half), radius - half))


# -- glow -------------------------------------------------------------------

_GLOW_STEP = 0.5


def paint_glow(p: QPainter, rect: QRectF, radius: float, colour: QColor,
               blur: float, spread: float = 0.0) -> None:
    """The halo of `box-shadow: 0 0 <blur>px <colour>` around a rounded box.

    A CSS shadow is the box blurred by a Gaussian of sigma blur/2, so along a
    straight edge its strength d px outside the box is half the complementary
    error function of d/sigma. Painted as nested fills from the outside in,
    each adding just enough alpha to reach that profile: no blur pass, no
    cache, and the same pixels on every platform. The box itself is opaque
    and is painted afterwards, so nothing is drawn under it.
    """
    alpha = colour.alphaF()
    if alpha <= 0.0 or blur <= 0.0:
        return
    sigma = blur / 2.0
    reach = 3.0 * sigma
    steps = int(math.ceil(reach / _GLOW_STEP))
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    base = QColor(colour)
    covered = 0.0
    for i in range(steps, 0, -1):
        d = i * _GLOW_STEP
        mid = d - _GLOW_STEP / 2.0
        target = alpha * 0.5 * math.erfc(mid / (sigma * math.sqrt(2.0)))
        if target <= covered:
            continue
        layer = 1.0 - (1.0 - target) / (1.0 - covered)
        covered = target
        if layer < 0.002:
            continue
        base.setAlphaF(layer)
        p.setBrush(base)
        grow = d + spread
        p.drawPath(rounded(rect.adjusted(-grow, -grow, grow, grow), radius + grow))
    p.restore()


# -- text -------------------------------------------------------------------

def _text(p: QPainter, rect: QRectF, text: str, font: QFont, colour: QColor,
          flags=Qt.AlignCenter) -> None:
    p.setFont(font)
    p.setPen(colour)
    p.drawText(rect, int(flags) | int(Qt.TextSingleLine), text)


def _text_shadow(p: QPainter, rect: QRectF, text: str, font: QFont, flags) -> None:
    """`text-shadow: 0 1px 3px rgba(0,0,0,.35)`: a soft dark copy one pixel
    down, built from a few faint offsets."""
    shade = tokens.rgba(0, 0, 0, 0.09)
    for dx, dy in ((0, 1), (-1, 1), (1, 1), (0, 0), (0, 2), (-1, 2), (1, 2)):
        _text(p, rect.translated(dx, dy), text, font, shade, flags)


# -- portrait content ---------------------------------------------------------

_silhouette_cache: dict[tuple, QPixmap] = {}


def tinted_silhouette(species: str | None, colour: str, device_px: int) -> QPixmap | None:
    """The race silhouette filled with `colour`, `device_px` square."""
    stem = cc_race_assets.asset_stem_for_species(species)
    if not stem or device_px <= 0:
        return None
    key = (stem, QColor(colour).name(), device_px)
    hit = _silhouette_cache.get(key)
    if hit is not None:
        return hit
    mask = cc_race_assets.load_race_pixmap(stem)
    if mask is None or mask.isNull():
        return None
    img = QImage(device_px, device_px, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    ip = QPainter(img)
    ip.setRenderHint(QPainter.SmoothPixmapTransform, True)
    scaled = mask.scaled(device_px, device_px, Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)
    ip.drawPixmap((device_px - scaled.width()) // 2,
                  (device_px - scaled.height()) // 2, scaled)
    ip.setCompositionMode(QPainter.CompositionMode_SourceIn)
    ip.fillRect(img.rect(), QColor(colour))
    ip.end()
    pm = QPixmap.fromImage(img)
    if len(_silhouette_cache) > 256:
        _silhouette_cache.clear()
    _silhouette_cache[key] = pm
    return pm


def _device_scale(p: QPainter) -> float:
    t = p.deviceTransform()
    return max(0.1, math.hypot(t.m11(), t.m12()))


def _paint_portrait_content(p: QPainter, circle: QRectF, border: float,
                            species: str | None, sil_colour: str,
                            portrait: QPixmap | None, dimmed: bool) -> None:
    if portrait is not None and not portrait.isNull():
        inner = circle.adjusted(border, border, -border, -border)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setClipPath(clip, Qt.IntersectClip)
        side = min(portrait.width(), portrait.height())
        src = QRectF((portrait.width() - side) / 2.0,
                     (portrait.height() - side) / 2.0, side, side)
        if dimmed:
            p.setOpacity(p.opacity() * 0.45)
        p.drawPixmap(inner, portrait, src)
        p.restore()
        return
    size = float(round(circle.width() * 0.62))
    px = int(round(size * _device_scale(p)))
    pm = tinted_silhouette(species, sil_colour, px)
    if pm is None:
        return
    target = glyphs.centred_square(circle, size)
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawPixmap(target, pm, QRectF(pm.rect()))
    p.restore()


# -- the two looks ----------------------------------------------------------

class StripPainter:
    """Shared structure; the two subclasses hold the look."""

    style: StripStyle

    # Blocks whose halo is painted in a first pass, under every block.
    def glow_tool(self, p, rect, c, on, tone=identity): ...
    def glow_identity(self, p, portrait_rect, name_rect, accent, dimmed): ...
    def glow_separator(self, p, rect): ...
    def glow_home(self, p, rect, is_open): ...

    def tool(self, p, rect, kind, on, tone=identity, hover=False): ...
    def keyset(self, p, rect, number, active, tone=identity, hover=False): ...
    def add(self, p, rect, hidden_sets, tone=identity, hover=False): ...
    def portrait(self, p, rect, accent, species, pixmap, dimmed): ...
    def name(self, p, rect, text, accent, dimmed): ...
    def separator(self, p, rect): ...

    # -- shared pieces --

    def _glyph(self, p: QPainter, rect: QRectF, kind: str, colour: QColor) -> None:
        s = self.style
        if kind == "keep_alive":
            glyphs.paint_bolt(p, glyphs.centred_square(rect, s.glyph_bolt), colour)
        elif kind == "click_sync":
            glyphs.paint_mouse(p, glyphs.centred_square(rect, s.glyph_mouse), colour)
        elif kind == "enable":
            glyphs.paint_power(p, glyphs.centred_square(rect, s.glyph_power), colour)
        elif kind == "add":
            glyphs.paint_plus(p, glyphs.centred_square(rect, s.glyph_plus), colour)

    def _number(self, p: QPainter, rect: QRectF, number: int, colour: QColor) -> None:
        _text(p, rect, str(number), strip_font(self.style.font_set_px, 800), colour)

    def _veil(self, p: QPainter, path: QPainterPath, hover: bool) -> None:
        if hover:
            p.fillPath(path, HOVER_VEIL)

    def _dot(self, p: QPainter, rect: QRectF, colour: QColor, tone: Tone) -> None:
        """6 px dot with a 1.5 px dark ring, 2 px in from the top right."""
        dot = QRectF(rect.right() - 2.0 - 6.0, rect.top() + 2.0, 6.0, 6.0)
        p.setPen(Qt.NoPen)
        p.setBrush(tone(tokens.rgba(0, 0, 0, 0.6)))
        p.drawEllipse(dot.adjusted(-1.5, -1.5, 1.5, 1.5))
        p.setBrush(tone(colour))
        p.drawEllipse(dot)

    def _hidden_dot(self, p: QPainter, rect: QRectF, tone: Tone) -> None:
        self._dot(p, rect, WHITE, tone)

    def warning_dot(self, p: QPainter, rect: QRectF, tone: Tone = identity) -> None:
        """Marks a block whose feature is switched on but not working."""
        self._dot(p, rect, QColor(tokens.WARNING), tone)

    def home(self, p: QPainter, rect: QRectF, icon: QPixmap | None,
             is_open: bool, stopped: bool) -> None:
        """The app icon clipped to a circle: no border, no backing fill."""
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if icon is not None and not icon.isNull():
            clip = QPainterPath()
            clip.addEllipse(rect)
            p.setClipPath(clip, Qt.IntersectClip)
            p.drawPixmap(rect, icon, QRectF(icon.rect()))
            if stopped:
                # grayscale(.5) brightness(.7), as a veil over the icon.
                p.fillRect(rect, tokens.rgba(0, 0, 0, 0.38))
        p.restore()

    @staticmethod
    def tool_colour(kind: str, on: bool) -> str:
        if kind == "keep_alive":
            return tokens.KEEP_ALIVE
        if kind == "click_sync":
            return tokens.CLICK_SYNC
        return tokens.ENABLE_ON if on else tokens.ENABLE_OFF


class NeonPainter(StripPainter):
    """Every block is a sign that is lit or unlit."""

    style = tokens.NEON_STYLE

    # -- glows --

    def glow_tool(self, p, rect, c, on, tone=identity):
        if on:
            paint_glow(p, rect, self.style.radius, tone(tr(c, 45)), 8.0)

    def glow_identity(self, p, portrait_rect, name_rect, accent, dimmed):
        if dimmed:
            return
        if name_rect is not None:
            paint_glow(p, name_rect, self.style.radius, tr(accent, 40), 8.0)
        paint_glow(p, portrait_rect, portrait_rect.width() / 2.0, tr(accent, 50), 9.0)

    def glow_separator(self, p, rect):
        paint_glow(p, rect, 1.0, tokens.rgba(255, 255, 255, 0.4), 4.0)

    def glow_home(self, p, rect, is_open):
        r = rect.width() / 2.0
        if is_open:
            paint_glow(p, rect, r, tr(tokens.BRAND_BLUE, 55), 10.0)
        else:
            paint_glow(p, rect, r, tr(tokens.BRAND_BLUE, 45), 8.0)

    # -- blocks --

    def _sign(self, p: QPainter, rect: QRectF, c: str, lit: bool, tone: Tone) -> QColor:
        """Fill and border of a lit or unlit sign; returns the glyph colour."""
        s = self.style
        path = rounded(rect, s.radius)
        p.setRenderHint(QPainter.Antialiasing, True)
        if lit:
            p.fillPath(path, tone(QColor(c)))
            _border(p, rounded, rect, s.radius, 2.0, tone(QColor(lt(c, 62))))
            return tone(WHITE)
        p.fillPath(path, QBrush(_toned_gradient(tokens.body_gradient(rect, c), tone)))
        _border(p, rounded, rect, s.radius, 2.0, tone(tr(c, 60)))
        return tone(QColor(lt(c, 55)))

    def tool(self, p, rect, kind, on, tone=identity, hover=False):
        ink = self._sign(p, rect, self.tool_colour(kind, on), on, tone)
        self._veil(p, rounded(rect, self.style.radius), hover)
        self._glyph(p, rect, kind, ink)

    def keyset(self, p, rect, number, active, tone=identity, hover=False):
        ink = self._sign(p, rect, tokens.set_color(number), active, tone)
        self._veil(p, rounded(rect, self.style.radius), hover)
        self._number(p, rect, number, ink)

    def add(self, p, rect, hidden_sets, tone=identity, hover=False):
        s = self.style
        path = rounded(rect, s.radius)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, tone(tokens.rgba(0, 0, 0, 0.45)))
        _border(p, rounded, rect, s.radius, 1.5,
                tone(tokens.rgba(255, 255, 255, 0.45)), dashed=True)
        self._veil(p, path, hover)
        self._glyph(p, rect, "add", tone(WHITE))
        if hidden_sets:
            self._hidden_dot(p, rect, tone)

    def portrait(self, p, rect, accent, species, pixmap, dimmed):
        s = self.style
        p.setRenderHint(QPainter.Antialiasing, True)
        circle = QPainterPath()
        circle.addEllipse(rect)
        if dimmed:
            p.fillPath(circle, QColor("#222222"))
            edge, sil = QColor("#555555"), "#777777"
        else:
            p.fillPath(circle, QBrush(tokens.body_gradient(rect, accent)))
            edge, sil = QColor(accent), lt(accent, 50)
        _paint_portrait_content(p, rect, s.portrait_border, species, sil, pixmap, dimmed)
        half = s.portrait_border / 2.0
        p.setPen(QPen(edge, s.portrait_border))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect.adjusted(half, half, -half, -half))

    def name(self, p, rect, text, accent, dimmed):
        s = self.style
        p.setRenderHint(QPainter.Antialiasing, True)
        path = right_rounded(rect, s.radius)
        if dimmed:
            p.fillPath(path, QColor("#222222"))
            edge = QColor("#555555")
        else:
            p.fillPath(path, QBrush(tokens.body_gradient(rect, accent)))
            edge = QColor(accent)
        _border(p, right_rounded, rect, s.radius, s.name_border, edge)
        area = rect.adjusted(s.name_border + s.name_pad_left, 0,
                             -(s.name_border + s.name_pad_right), 0)
        flags = Qt.AlignLeft | Qt.AlignVCenter
        font = name_font(s)
        _text_shadow(p, area, text, font, flags)
        _text(p, area, text, font, WHITE, flags)

    def separator(self, p, rect):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(rounded(rect, 1.0), WHITE)

    def home(self, p, rect, icon, is_open, stopped):
        super().home(p, rect, icon, is_open, stopped)
        if is_open:
            # box-shadow spread: a 2 px ring OUTSIDE the circle.
            p.save()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor(lt(tokens.BRAND_BLUE, 62)), 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(-1.0, -1.0, 1.0, 1.0))
            p.restore()


class FlatPainter(StripPainter):
    """Solid fills. No borders or glows anywhere."""

    style = tokens.FLAT_STYLE

    def glow_tool(self, p, rect, c, on, tone=identity):
        return

    def glow_identity(self, p, portrait_rect, name_rect, accent, dimmed):
        return

    def glow_separator(self, p, rect):
        return

    def glow_home(self, p, rect, is_open):
        return

    def tool(self, p, rect, kind, on, tone=identity, hover=False):
        c = self.tool_colour(kind, on)
        path = rounded(rect, self.style.radius)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, QColor(c if on else dk(c, 30)))
        self._veil(p, path, hover)
        self._glyph(p, rect, kind, WHITE if on else tokens.rgba(255, 255, 255, 0.5))

    def keyset(self, p, rect, number, active, tone=identity, hover=False):
        c = tokens.set_color(number)
        s = self.style
        path = rounded(rect, s.radius)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, QColor(c if active else dk(c, 46)))
        self._veil(p, path, hover)
        if active:
            _border(p, rounded, rect, s.radius, 2.0, WHITE)   # inset ring
        self._number(p, rect, number,
                     WHITE if active else tokens.rgba(255, 255, 255, 0.72))

    def add(self, p, rect, hidden_sets, tone=identity, hover=False):
        path = rounded(rect, self.style.radius)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, QColor("#2e2e2e"))
        self._veil(p, path, hover)
        self._glyph(p, rect, "add", WHITE)
        if hidden_sets:
            self._hidden_dot(p, rect, identity)

    def portrait(self, p, rect, accent, species, pixmap, dimmed):
        s = self.style
        p.setRenderHint(QPainter.Antialiasing, True)
        circle = QPainterPath()
        circle.addEllipse(rect)
        if dimmed:
            p.fillPath(circle, QColor("#777777"))
            edge, sil = QColor("#4a4a4a"), "#2a2a2a"
        else:
            p.fillPath(circle, QColor(lt(accent, 55)))
            edge, sil = QColor(accent), dk(accent, 42)
        _paint_portrait_content(p, rect, s.portrait_border, species, sil, pixmap, dimmed)
        half = s.portrait_border / 2.0
        p.setPen(QPen(edge, s.portrait_border))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect.adjusted(half, half, -half, -half))

    def name(self, p, rect, text, accent, dimmed):
        s = self.style
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(right_rounded(rect, s.radius),
                   QColor("#4a4a4a" if dimmed else accent))
        area = rect.adjusted(s.name_pad_left, 0, -s.name_pad_right, 0)
        _text(p, area, text, name_font(s), WHITE, Qt.AlignLeft | Qt.AlignVCenter)

    def separator(self, p, rect):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(rounded(rect, 1.0), tokens.rgba(255, 255, 255, 0.8))

    def home(self, p, rect, icon, is_open, stopped):
        super().home(p, rect, icon, is_open, stopped)
        if is_open:
            p.save()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(WHITE, 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(-1.0, -1.0, 1.0, 1.0))
            p.restore()


def painter_for(style: StripStyle) -> StripPainter:
    return NeonPainter() if style.is_neon else FlatPainter()


def paint_number_block(p: QPainter, rect: QRectF, number: int, lit: bool,
                       look: str = tokens.NEON, glow: bool = True,
                       hover: bool = False) -> None:
    """One numbered keyset block on its own, for anything that shows keysets
    the way the strip does (no StripWidget needed).

    `rect` is the block (28 px square in Neon, 26 in Flat, in the painter's
    units). `lit` is the active state. Neon draws a halo around a lit block
    unless `glow` is False; leave about 12 px free around the block for it.
    """
    painter = painter_for(tokens.style_for(look))
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    if glow:
        painter.glow_tool(p, rect, tokens.set_color(number), lit)
    painter.keyset(p, rect, number, lit, identity, hover)
    p.restore()
