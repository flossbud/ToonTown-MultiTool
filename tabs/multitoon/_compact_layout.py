"""Pinwheel layout for the Multitoon tab.

Four controlled-toon cards pinwheel around a central app-icon emblem: each
card's inner corner is carved concave by a circular cutout so the emblem nests
into the middle. A broadcast status bar runs across the bottom.

This is the single Multitoon layout at every window size (the old compact/full
split is retired). It reuses the per-slot widgets owned by `MultitoonTab`
(`tab.toon_buttons`, `tab.slot_badges`, ...) - reparenting + restyling them into
the pinwheel arrangement on `populate()` - so all signal wiring and per-toon
state survive. `MultitoonTab` drives rendering through `set_card_brand`.

Two behaviours differ from the legacy stack (per the design handoff):
  * Stopping the broadcast service dims every card in place (the cards keep
    their toon identity); cards only empty out when the game window closes.
  * Turning an individual toon's Enable toggle off dims just that one card.
Both are expressed by the per-card lit/dimmed treatment driven from
`set_card_brand`; `MultitoonTab` owns the state.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import (
    Qt, QSize, QRect, QRectF, QPoint, QPointF, Property, QPropertyAnimation,
    QEasingCurve, Signal, QTimer, QEvent,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
)

from tabs.multitoon._layout_utils import clear_layout
from utils.color_math import darken_rgb
from utils.overlay.card_metrics import CardMetrics
from utils.overlay.gestures import is_drag


def _resolve_body_base(entry: dict, accent: QColor) -> QColor:
    """Return the color to use as the card body gradient base.

    If the customization entry carries a separate `body` override, that
    color drives the fill. Otherwise the accent does, preserving the
    existing behavior (body == accent-derived gradient).
    """
    from utils.toon_customization_resolve import resolve_body
    override = resolve_body(entry)
    return override if override is not None else QColor(accent)


# ── Geometry ────────────────────────────────────────────────────────────────
# CardMetrics(1.0) is the canonical source for EVERY card dimension: at scale
# 1.0 it yields exactly the integer values the design handoff specified, so
# framed mode is byte-for-byte unchanged. The module-level constants below are
# the canonical 1.0 exports (a couple of paths + tests read them); a live card
# instance sources its sizes from its OWN CardMetrics (default 1.0) so it can be
# re-scaled via apply_metrics() without touching this module.
_METRICS = CardMetrics(1.0)

CARD_RADIUS = _METRICS.card_radius
CARD_BORDER = _METRICS.card_border
# NOTE: CARD_PAD / CARD_MIN_H / GRID_GAP / CTRL_W have no live consumer inside
# this module anymore (the layout reads self._metrics.*), but they are the
# canonical 1.0 exports asserted by tests/test_compact_layout_paths.py
# (the value-object-as-single-source-of-truth contract); keep them.
CARD_PAD = _METRICS.card_pad
CARD_MIN_H = _METRICS.card_min_h
GRID_GAP = _METRICS.grid_gap

PORTRAIT = _METRICS.portrait
PORTRAIT_RING = _METRICS.portrait_ring
CUTOUT_R = _METRICS.cutout_r
EMBLEM = _METRICS.emblem

CTRL_W = _METRICS.ctrl_w
TOGGLE_W, TOGGLE_H = _METRICS.toggle_w, _METRICS.toggle_h
KA_PILL_H = _METRICS.ka_pill_h
KEYSET_H = _METRICS.keyset_h
KA_DOT = _METRICS.ka_dot              # lightning toggle diameter inside the KA pill

STATUS_TOP_MARGIN = _METRICS.status_top_margin

# Net-new design constant: keep-alive orange (the theme's `accent_orange`
# #c47a2a reads too brown for this surface). Border tint pairs with it.
KA_ORANGE = "#ff9500"
KA_ORANGE_BORDER = "#ffb04d"

# Per-quadrant configuration, indexed by slot 0..3 (tl, tr, bl, br).
#   cutout   : which card-local corner the concave circle is centred on
#   left     : True -> portrait hugs the left edge, controls toward centre
#   stack_bottom : True -> name/stats row sits ABOVE the portrait+controls row
_CFG = [
    {"cutout": "br", "left": True,  "stack_bottom": False},   # 0 top-left
    {"cutout": "bl", "left": False, "stack_bottom": False},   # 1 top-right
    {"cutout": "tr", "left": True,  "stack_bottom": True},    # 2 bottom-left
    {"cutout": "tl", "left": False, "stack_bottom": True},    # 3 bottom-right
]


def _app_icon_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "assets", "multitool.png")


def _card_body_path(
    w: float, h: float, cutout: str,
    radius: float = CARD_RADIUS, cutout_r: float = CUTOUT_R,
) -> QPainterPath:
    """The card body outline: a rounded rect with one corner carved out by a
    circle. Shared by the card background and the glow so both follow the exact
    same shape (including the concave cutout). `radius` and `cutout_r` are
    sourced from a CardMetrics so the shape scales with the card; the defaults
    are the canonical 1.0 values (rounded corner 20px, concave bite 96px)."""
    rect = QRectF(0.5, 0.5, w - 1, h - 1)
    rounded = QPainterPath()
    rounded.addRoundedRect(rect, radius, radius)
    corners = {
        "tl": QPointF(0, 0), "tr": QPointF(w, 0),
        "bl": QPointF(0, h), "br": QPointF(w, h),
    }
    cut = QPainterPath()
    cut.addEllipse(corners[cutout], cutout_r, cutout_r)
    return rounded.subtracted(cut)


# Accent glow. We PAINT it (a gaussian blur of the card shape, blitted behind
# the cards) rather than use a QGraphicsDropShadowEffect: on macOS the effect's
# output is clipped to the cell's square bounds, leaving sharp square corners
# behind the rounded card. A painted pixmap has no such clipping, so the glow
# follows the rounded body + concave cutout exactly.
GLOW_BLUR = _METRICS.glow_blur   # gaussian radius (smaller = tighter, less visible)
GLOW_ALPHA = 105        # peak accent alpha of the glow source (lower = fainter)
# Padding the grid keeps around the cards so the painted halo has room to fade.
# GLOW_ROOM is the grid host's *layout headroom* (a contents margin around the
# whole 2x2 cluster), not a per-card geometry. It is deliberately NOT scaled by
# apply_metrics: in framed mode apply_metrics is only ever called at scale 1.0,
# and in overlay mode each card lives in its own surface that supplies its own
# margin, so a scaled grid margin would have no consumer. The glow *blur* (the
# halo softness) IS scaled per CardMetrics.glow_blur, which is the proportional
# part that actually shows.
GLOW_ROOM = 34

# Bound the _GlowLayer pixmap cache (LRU). Each entry is a blurred QPixmap keyed
# by (size, cutout, accent, radius, cutout_r, blur); without a cap, repeated
# rescale / theme / accent changes would accumulate large pixmaps unbounded. 24
# keeps a generous working set (4 cards x a few recent scales/accents) while the
# least-recently-used entries are evicted.
_GLOW_CACHE_MAX = 24


def _make_glow_pixmap(
    w: int, h: int, cutout: str, accent: QColor,
    radius: float = CARD_RADIUS, cutout_r: float = CUTOUT_R, blur: float = GLOW_BLUR,
):
    """Return (pixmap, pad): the card shape filled with `accent` and gaussian-
    blurred on a transparent canvas padded by `pad`. Blit at (x - pad, y - pad)
    to lay a soft accent halo around the card that follows its exact shape. The
    body radii + blur are sourced from a CardMetrics so the halo scales with the
    card (defaults reproduce the canonical 1.0 halo)."""
    from PySide6.QtWidgets import (
        QGraphicsScene, QGraphicsBlurEffect, QGraphicsPixmapItem,
    )
    pad = int(blur * 2.5)
    pw, ph = int(w + 2 * pad), int(h + 2 * pad)
    src = QPixmap(pw, ph)
    src.fill(Qt.transparent)
    p = QPainter(src)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    path = _card_body_path(w, h, cutout, radius, cutout_r)
    path.translate(pad, pad)
    col = QColor(accent)
    col.setAlpha(GLOW_ALPHA)
    p.fillPath(path, col)
    p.end()

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(src)
    blur_eff = QGraphicsBlurEffect()
    blur_eff.setBlurRadius(blur)
    item.setGraphicsEffect(blur_eff)
    scene.addItem(item)
    out = QPixmap(pw, ph)
    out.fill(Qt.transparent)
    p2 = QPainter(out)
    scene.render(p2, QRectF(0, 0, pw, ph), QRectF(0, 0, pw, ph))
    p2.end()
    scene.removeItem(item)
    return out, pad


class _GlowLayer(QWidget):
    """Paints each lit card's accent halo (a cached gaussian pixmap of the card
    shape). Lives behind the cards spanning the grid, so the halos are never
    clipped to a square and follow the rounded body + cutout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._cards = []   # [{"x","y","pm","pad"}]
        # LRU cache of blurred halo pixmaps, bounded to _GLOW_CACHE_MAX entries
        # so repeated rescale / theme / accent churn cannot accumulate large
        # QPixmaps without limit. Key: (w,h,cutout,accent_rgba,radius,cutout_r,blur).
        self._cache: "OrderedDict" = OrderedDict()
        self._blur = GLOW_BLUR

    def set_blur(self, blur: float) -> None:
        """Set the gaussian halo radius (scaled per CardMetrics.glow_blur)."""
        self._blur = blur

    def set_cards(self, specs) -> None:
        cards = []
        for s in specs:
            w, h = int(s["w"]), int(s["h"])
            if w <= 0 or h <= 0:
                continue
            rw, rh = ((w + 7) // 8) * 8, ((h + 7) // 8) * 8   # round so drags reuse cache
            accent = QColor(s["accent"])
            radius = s.get("radius", CARD_RADIUS)
            cutout_r = s.get("cutout_r", CUTOUT_R)
            key = (rw, rh, s["cutout"], accent.rgba(), radius, cutout_r, self._blur)
            entry = self._cache.get(key)
            if entry is None:
                entry = _make_glow_pixmap(
                    rw, rh, s["cutout"], accent, radius, cutout_r, self._blur
                )
                self._cache[key] = entry
                if len(self._cache) > _GLOW_CACHE_MAX:
                    self._cache.popitem(last=False)   # evict least-recently used
            else:
                self._cache.move_to_end(key)          # mark most-recently used
            pm, pad = entry
            cards.append({"x": s["x"], "y": s["y"], "pm": pm, "pad": pad})
        self._cards = cards
        self.update()

    def paintEvent(self, event):
        if not self._cards:
            return
        p = QPainter(self)
        for c in self._cards:
            p.drawPixmap(int(c["x"] - c["pad"]), int(c["y"] - c["pad"]), c["pm"])
        p.end()


# ── Card background (custom paint: concave cutout + accent gradient) ────────
class _QuadCardBackground(QWidget):
    """Paints one card body: a 20px rounded rect with one corner carved out by
    a 96px circle, filled with a deep body-color gradient and bordered by a 5px
    inner accent stroke. The carved corner lets the central emblem nest in.

    The body fill and the accent border are independent: `accent` drives the
    5px border, portrait ring, glow, and status dot; `body` (optional) drives
    the fill gradient. When `body` is None the fill gradient derives from
    `accent` (the original behavior).

    Has no graphics effect of its own (the glow/dim effects live on ancestor
    frames), so this never trips the "one painter per device" conflict.
    """

    def __init__(self, cutout: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Defeat the app-global `QWidget { background-color }` rule so the
        # carved cutout reads as transparent (only the painted body shows).
        self.setStyleSheet("background: transparent;")
        self._cutout = cutout
        self._accent = QColor("#555555")
        self._body: QColor | None = None
        self._dimmed = True
        self._peek_opacity = 1.0  # transparent-mode hover-peek body translucency
        # Painted-body radii + border width, sourced from a CardMetrics so the
        # shape scales with the card (defaults = canonical 1.0 values).
        self._radius = CARD_RADIUS
        self._cutout_r = CUTOUT_R
        self._border = CARD_BORDER

    def configure(
        self, accent: QColor, dimmed: bool, body: "QColor | None" = None
    ) -> None:
        self._accent = QColor(accent)
        self._body = QColor(body) if body is not None else None
        self._dimmed = bool(dimmed)
        self.update()

    def apply_metrics(self, metrics) -> None:
        """Re-source the painted-body radii + border from `metrics` and repaint.
        Idempotent; the colour/dim state set by configure() is preserved."""
        self._radius = metrics.card_radius
        self._cutout_r = metrics.cutout_r
        self._border = metrics.card_border
        self.update()

    def _body_path(self) -> QPainterPath:
        return _card_body_path(
            self.width(), self.height(), self._cutout, self._radius, self._cutout_r
        )

    def set_peek_opacity(self, opacity: float) -> None:
        """Hover-peek body translucency (1.0 = opaque). The card body fades so the
        game shows through, while the controls (separate widgets) stay opaque."""
        opacity = float(opacity)
        if opacity != self._peek_opacity:
            self._peek_opacity = opacity
            self.update()

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        if self._peek_opacity < 1.0:
            p.setOpacity(self._peek_opacity)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = self._body_path()

        # Body gradient: deep, rich version of the body-fill base. darken()
        # multiplies each channel; the dim treatment scales brightness down
        # further (the saturation half of saturate(0.45) is handled by the
        # colorize effect). When no separate body override is set, the accent
        # drives the fill (original behavior).
        body_base = self._body if self._body is not None else self._accent
        bright = 0.75 if self._dimmed else 1.0
        top = darken_rgb(darken_rgb(body_base, 0.28), bright)
        bot = darken_rgb(darken_rgb(body_base, 0.14), bright)
        grad = QLinearGradient(0, 0, self.width() * 0.38, self.height())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.fillPath(path, grad)

        # 5px inner border: accent-colored, stroke the body path at double
        # width and clip to the path so only the inner half survives - a
        # clean border that follows the concave curve.
        border = darken_rgb(self._accent, 0.62) if self._dimmed else self._accent
        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, self._border * 2))
        p.drawPath(path)
        p.restore()
        p.end()


# ── Portrait frame (4px accent ring + dark inner disc around the portrait) ──
class _PortraitFrame(QWidget):
    """172px circular frame: dark inner disc + 4px accent ring, hosting the
    shared ToonPortraitWidget inset inside the ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Diameter + ring width source from a CardMetrics so the frame scales
        # (defaults = canonical 1.0 values: 172px disc, 4px ring).
        self._size = PORTRAIT
        self._ring_w = PORTRAIT_RING
        self.setFixedSize(self._size, self._size)
        self.setStyleSheet("background: transparent;")
        self._ring = QColor("#555555")
        self._dimmed = True
        self._peek_opacity = 1.0   # extra hover-peek dim for the circular frame

    def set_peek_opacity(self, opacity: float) -> None:
        opacity = float(opacity)
        if opacity != self._peek_opacity:
            self._peek_opacity = opacity
            self.update()

    def configure(self, ring: QColor, dimmed: bool) -> None:
        self._ring = QColor(ring)
        self._dimmed = bool(dimmed)
        self.update()

    def apply_metrics(self, metrics) -> None:
        """Re-size the frame + ring width from `metrics` and repaint. The host
        (the portrait badge inset) must be re-fit by the caller via
        host_geometry()."""
        self._size = metrics.portrait
        self._ring_w = metrics.portrait_ring
        self.setFixedSize(self._size, self._size)
        self.update()

    def host_geometry(self) -> tuple[int, int, int, int]:
        inset = self._ring_w
        return (inset, inset, self._size - 2 * inset, self._size - 2 * inset)

    def paintEvent(self, event):
        p = QPainter(self)
        if self._peek_opacity < 1.0:
            p.setOpacity(self._peek_opacity)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = cy = self._size / 2.0
        # Dark inner background (rgba(0,0,0,0.22)).
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 56))
        p.drawEllipse(QPointF(cx, cy), cx - 0.5, cy - 0.5)
        # accent ring on the outer edge.
        ring = darken_rgb(self._ring, 0.62) if self._dimmed else self._ring
        pen = QPen(ring, self._ring_w)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = (self._size - self._ring_w) / 2.0
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ── Central emblem (app icon nested in the grid centre) ────────────────────
class _Emblem(QWidget):
    """156px circle: opaque bg-app fill + app icon, with a pulsing blue ring
    when broadcasting. Passive by default; call set_interactive(True) to enable
    toggle/drag/resize gestures."""

    toggle_requested = Signal()
    move_requested = Signal()
    resize_scrolled = Signal(int)

    _RING_MARGIN = 14  # room for the -4px ring + soft glow outside the disc
    _BASE_ICON_INSET = 8  # app-icon inset inside the disc at scale 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        # Disc diameter + ring margin + icon inset source from a CardMetrics so
        # the emblem scales (defaults = canonical 1.0: 156px disc, 14 margin).
        self._d = EMBLEM
        self._ring_margin = self._RING_MARGIN
        self._icon_inset = self._BASE_ICON_INSET
        self._scale = 1.0  # decorative ring offsets + pen widths scale with this
        side = self._d + 2 * self._ring_margin
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._armed = False
        self._dragging = False
        self._press = None

        # Single-shot dwell timer: fires after ~300ms hover to arm the emblem
        # for scroll-to-resize. Created unconditionally; only started when
        # interactive (enterEvent) so passive mode is unaffected.
        self._dwell_timer = QTimer(self)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.setInterval(300)
        self._dwell_timer.timeout.connect(self._on_dwell_timeout)

        self._broadcasting = False
        self._bg_app = QColor("#1a1a1a")
        self._ring = QColor("#0077ff")
        self._pulse = 1.0

        icon = QPixmap(_app_icon_path())
        # Cap the source at the display size so the one-time grey pass below
        # iterates ~160x160 pixels, not the full-res art.
        if not icon.isNull() and max(icon.width(), icon.height()) > 160:
            icon = icon.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._icon = icon
        self._icon_grey = self._build_grey(self._icon)

        # Smooth ping-pong pulse 1 -> 0.45 -> 1 over ~2.4s, looping forever.
        # Keyframes (not a finished-handler bounce) so there is no stale-anim
        # access at teardown.
        self._anim = QPropertyAnimation(self, b"pulse")
        self._anim.setDuration(2400)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.setKeyValueAt(0.0, 1.0)
        self._anim.setKeyValueAt(0.5, 0.45)
        self._anim.setKeyValueAt(1.0, 1.0)
        self._anim.setLoopCount(-1)

    @staticmethod
    def _build_grey(pm: QPixmap) -> QPixmap:
        """Desaturated + dimmed copy of the icon for the idle state."""
        if pm.isNull():
            return pm
        img = pm.toImage().convertToFormat(img_fmt())
        for y in range(img.height()):
            for x in range(img.width()):
                c = QColor(img.pixelColor(x, y))
                if c.alpha() == 0:
                    continue
                lum = int(0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue())
                # grayscale(0.5) brightness(0.7): mix halfway to luminance, *0.7
                r = int((c.red() * 0.5 + lum * 0.5) * 0.7)
                g = int((c.green() * 0.5 + lum * 0.5) * 0.7)
                b = int((c.blue() * 0.5 + lum * 0.5) * 0.7)
                img.setPixelColor(x, y, QColor(r, g, b, c.alpha()))
        return QPixmap.fromImage(img)

    def get_pulse(self) -> float:
        return self._pulse

    def set_pulse(self, v: float) -> None:
        self._pulse = float(v)
        self.update()

    pulse = Property(float, get_pulse, set_pulse)

    def configure(self, broadcasting: bool, bg_app: str, ring: str) -> None:
        self._bg_app = QColor(bg_app)
        self._ring = QColor(ring)
        if broadcasting != self._broadcasting:
            self._broadcasting = broadcasting
            if broadcasting:
                self._anim.start()
            else:
                self._anim.stop()
                self._pulse = 1.0
        self.update()

    def apply_metrics(self, metrics) -> None:
        """Re-size the emblem disc + ring margin + icon inset from `metrics` and
        repaint. The app-icon pixmaps are re-scaled at paint time (no rebuild),
        so this is cheap and idempotent."""
        self._d = metrics.emblem
        self._ring_margin = metrics.icon_px(self._RING_MARGIN)
        self._icon_inset = metrics.icon_px(self._BASE_ICON_INSET)
        self._scale = metrics.scale
        side = self._d + 2 * self._ring_margin
        self.setFixedSize(side, side)
        self.update()

    def stop(self) -> None:
        self._anim.stop()

    # --- Interactivity ---

    def set_interactive(self, on: bool) -> None:
        """Enable (on=True) or disable (on=False) mouse interaction.
        Default is passive (WA_TransparentForMouseEvents set)."""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        self._armed = False

    def _on_dwell_timeout(self) -> None:
        self._armed = True
        self.update()

    def enterEvent(self, event):
        self._dwell_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._dwell_timer.stop()
        self._armed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and not self._dragging:
            if is_drag(self._press, event.position().toPoint()):
                self._dragging = True
                self.move_requested.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            self.toggle_requested.emit()
        self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._armed:
            self.resize_scrolled.emit(1 if event.angleDelta().y() > 0 else -1)
        else:
            event.ignore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        cx = cy = self.width() / 2.0
        r = self._d / 2.0

        # Pulsing ring + soft glow just outside the disc (broadcasting only).
        # Offsets + pen widths scale with the emblem so the decorative extent
        # stays inside the (scaled) ring margin at every scale (no clipping).
        if self._broadcasting:
            ring_off = 4 * self._scale
            glow = QColor(self._ring)
            glow.setAlphaF(0.55 * self._pulse)
            p.setPen(QPen(glow, 8 * self._scale))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + ring_off, r + ring_off)
            ring = QColor(self._ring)
            ring.setAlphaF(self._pulse)
            p.setPen(QPen(ring, 2 * self._scale))
            p.drawEllipse(QPointF(cx, cy), r + ring_off, r + ring_off)

        # Opaque bg-app disc so the carved card cutouts read as a clean ring.
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_app)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # App icon, inset 8px, clipped circular.
        pm = self._icon if self._broadcasting else self._icon_grey
        if not pm.isNull():
            inset = self._icon_inset
            d = self._d - 2 * inset
            clip = QPainterPath()
            clip.addEllipse(QPointF(cx, cy), d / 2.0, d / 2.0)
            p.setClipPath(clip)
            target = QRectF(cx - d / 2.0, cy - d / 2.0, d, d)
            scaled = pm.scaled(int(d), int(d), Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
            p.drawPixmap(target, scaled, QRectF(scaled.rect()))

        # Armed ring: thin static outer ring shown when dwell-armed for resize.
        if self._armed:
            p.setClipping(False)
            armed_off = 9 * self._scale
            armed_color = QColor(self._ring)
            armed_color.setAlphaF(0.85)
            p.setPen(QPen(armed_color, 2 * self._scale))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + armed_off, r + armed_off)

        p.end()


def img_fmt():
    from PySide6.QtGui import QImage
    return QImage.Format_ARGB32


# ── Slot save/restore (transparent-mode reparent foundation, Task 4.1b) ──────
@dataclass
class SlotRecord:
    """Snapshot of a widget's EXACT place in the pinwheel, enough to reinsert it
    byte-for-byte after a transactional reparent away (Task 4.1b reparents the
    cards + emblem into per-window overlay surfaces on transparent-mode enter and
    restores them to the tab on leave).

    Two shapes, picked by a `kind` discriminator:
      * "grid"   - a grid-managed card (one of the 4 QFrames): captured grid +
        row/col/spans + the layout-item alignment, so restore re-inserts it at
        the same cell.
      * "manual" - the manually-positioned, raised emblem (NOT in the grid):
        captured geometry + z-order, so restore re-parents it and restacks it
        above the cards.

    The record keeps a reference to the widget itself, so restore_slot needs only
    the record. `size_policy` is held by value (a copied QSizePolicy) so a later
    mutation of the live widget's policy cannot corrupt the snapshot.
    """

    widget: QWidget
    kind: str                       # "grid" | "manual"
    parent: "QWidget | None"
    visible: bool
    size_policy: QSizePolicy
    # grid case
    grid: "QGridLayout | None" = None
    row: int = 0
    col: int = 0
    row_span: int = 1
    col_span: int = 1
    alignment: object = None        # Qt.Alignment captured from the layout item
    # manual (emblem) case
    geometry: "QRect | None" = None
    pos: "QPoint | None" = None
    raised: bool = False


# ── The layout ─────────────────────────────────────────────────────────────
class _CompactLayout(QWidget):
    """Pinwheel Multitoon layout. Public surface consumed by MultitoonTab:
    `populate`, `set_card_brand`, `apply_theme`, `_set_keep_alive_collapsed`,
    `_animate_keep_alive_visibility`, `deactivate`, `_position_cards`."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        # Canonical card geometry for this layout. At scale 1.0 every value
        # equals the module-level sizing constants; layout build sites source
        # their sizes from here so the value object is the single source of truth.
        self._metrics = CardMetrics(1.0)
        self._cells: list[dict] = []
        # Position-based content routing: slot i's content lives in cell shell
        # _slot_to_cell[i] (identity until a non-contiguous window arrangement -
        # e.g. a vertical stack - routes content into a different shell). The
        # shells themselves never move or change shape; only which slot's widgets
        # they hold changes. See apply_cell_permutation.
        self._slot_to_cell: list[int] = [0, 1, 2, 3]
        self._emblem: _Emblem | None = None
        self._glow: _GlowLayer | None = None
        self._grid_host: QWidget | None = None
        self._grid: QGridLayout | None = None
        self._outer: QVBoxLayout | None = None
        self._build_structure()
        self.populate()

    @property
    def _card_slots(self) -> list[dict]:
        """Alias for _cells; consumed by MultitoonTab and tests."""
        return self._cells

    # ── Structure ──────────────────────────────────────────────────────────
    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(0)
        self._outer = outer   # scaled by apply_metrics (8,6,8,8 at scale 1.0)

        # Grid host holds the painted glow layer, the 2x2 cards, and the centre
        # emblem. The grid's inner margin gives each painted halo room to fade.
        self._grid_host = QWidget()
        # Defeat the app-global `QWidget { background-color }` rule so the cluster
        # container is transparent in the floating overlay (no visible change in
        # framed mode, where it sits over the dark app background anyway).
        self._grid_host.setStyleSheet("background: transparent;")
        grid = QGridLayout(self._grid_host)
        self._grid = grid
        grid.setContentsMargins(GLOW_ROOM, GLOW_ROOM, GLOW_ROOM, GLOW_ROOM)
        grid.setSpacing(self._metrics.grid_gap)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        for row in range(2):
            grid.setRowStretch(row, 1)

        # Glow layer spans the grid host, behind the (transparent) cards.
        self._glow = _GlowLayer(self._grid_host)

        for i in range(4):
            cell = self._build_cell(i)
            grid.addWidget(cell["cell"], i // 2, i % 2)

        self._emblem = _Emblem(self._grid_host)
        self._emblem.raise_()

        outer.addWidget(self._grid_host, 1)

        # Bottom broadcast status bar (reuses the shared ServiceStatusBar).
        self._status_host = QHBoxLayout()
        self._status_host.setContentsMargins(0, STATUS_TOP_MARGIN, 0, 0)
        outer.addLayout(self._status_host)

    def _build_cell(self, i: int) -> dict:
        cfg = _CFG[i]

        # cell: the card QFrame; a CardDimOverlay sibling is lazy-created on the
        # first _apply_cell_effects call (stored in cell["dim"]) and painted on
        # top when the card is inactive (proxy-safe, replaces the old colorize).
        cell = QFrame()
        cell.setObjectName(f"pin_cell_{i}")
        cell.setStyleSheet(f"#pin_cell_{i} {{ background: transparent; border: none; }}")
        cell.setMinimumSize(0, self._metrics.card_min_h)
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # The painted body + status dot are MANUALLY positioned (not in a layout),
        # normally re-placed by the parent layout's resizeEvent -> _relayout_all. In
        # transparent mode the cell is reparented OUT into a per-card surface, so the
        # parent never sees its resize; filter the cell's OWN resize so the body
        # always tracks the cell size (else content spills past the body).
        cell.installEventFilter(self)

        # glow_host holds the accent drop-shadow (attached only when the card is
        # lit). Its only child is the card background, so the shadow renders the
        # card shape and is not invalidated by the animating controls (those live
        # in the content layer, a sibling of glow_host).
        glow_host = QWidget(cell)
        glow_host.setStyleSheet("background: transparent;")
        bg = _QuadCardBackground(cfg["cutout"], glow_host)

        # ── Structural layout tree, assembled ONCE. populate() only refills
        # the leaf layouts (toggle_row / ka_lay / sel_holder / name_holder /
        # stats_row) with the shared per-slot widgets, so the structural
        # nesting is never re-parented (which would warn on a 2nd populate). ──
        content = QVBoxLayout(cell)
        pad = self._metrics.card_pad
        content.setContentsMargins(pad, pad, pad, pad)
        content.setSpacing(12)

        portrait_frame = _PortraitFrame(cell)

        # Controls column: 3 toggles, KA pill, keyset pill.
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(9)
        toggle_row.setContentsMargins(0, 0, 0, 0)

        ka_pill = QFrame()
        ka_pill.setObjectName(f"ka_pill_{i}")
        ka_pill.setFixedHeight(KA_PILL_H)
        ka_lay = QHBoxLayout(ka_pill)
        ka_lay.setContentsMargins(5, 0, 11, 0)
        ka_lay.setSpacing(9)

        sel_holder = QHBoxLayout()
        sel_holder.setContentsMargins(0, 0, 0, 0)
        sel_holder.setSpacing(0)

        ctrl_col = QVBoxLayout()
        ctrl_col.setSpacing(10)
        ctrl_col.setContentsMargins(0, 0, 0, 0)
        ctrl_col.addLayout(toggle_row)
        ctrl_col.addWidget(ka_pill)
        ctrl_col.addLayout(sel_holder)
        ctrl_wrap = QWidget()
        ctrl_wrap.setFixedWidth(self._metrics.ctrl_w)
        # Transparent so the controls sit directly on the accent body instead
        # of a grey panel (the global QWidget rule would otherwise fill it).
        ctrl_wrap.setStyleSheet("background: transparent;")
        ctrl_wrap.setLayout(ctrl_col)

        # Body row: portrait hugs the outer edge, controls toward the centre.
        v_align = Qt.AlignBottom if cfg["stack_bottom"] else Qt.AlignTop
        body_row = QHBoxLayout()
        body_row.setSpacing(10)
        body_row.setContentsMargins(0, 0, 0, 0)
        if cfg["left"]:
            body_row.addWidget(portrait_frame, 0, v_align)
            body_row.addStretch(1)
            body_row.addWidget(ctrl_wrap, 0, v_align)
        else:
            body_row.addWidget(ctrl_wrap, 0, v_align)
            body_row.addStretch(1)
            body_row.addWidget(portrait_frame, 0, v_align)

        # Meta: name + stats, aligned to the card's outer edge.
        name_holder = QHBoxLayout()
        name_holder.setContentsMargins(0, 0, 0, 0)
        name_holder.setSpacing(0)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        stats_row.setContentsMargins(0, 0, 0, 0)
        meta_col = QVBoxLayout()
        meta_col.setSpacing(5)
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.addLayout(name_holder)
        meta_col.addLayout(stats_row)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.addLayout(meta_col, 1)

        # The bottom quadrants read [meta] then [portrait+controls].
        if cfg["stack_bottom"]:
            content.addLayout(meta_row)
            content.addLayout(body_row, 1)
        else:
            content.addLayout(body_row, 1)
            content.addLayout(meta_row)

        self._cells.append({
            "cell": cell,
            "glow_host": glow_host,
            "bg": bg,
            "content": content,      # card content QVBoxLayout (card_pad margins)
            "ctrl_col": ctrl_col,    # controls column QVBoxLayout (scaled spacing)
            "body_row": body_row,    # portrait+controls row (scaled gap)
            "meta_col": meta_col,    # name+stats column (scaled spacing)
            "ctrl_wrap": ctrl_wrap,  # fixed-width controls column (ctrl_w)
            "portrait_frame": portrait_frame,
            "toggle_row": toggle_row,
            "ka_pill": ka_pill,
            "ka_group": ka_pill,  # alias consumed by MultitoonTab
            "ka_lay": ka_lay,
            "sel_holder": sel_holder,
            "name_holder": name_holder,
            "stats_row": stats_row,
            "cfg": cfg,
            "content_slot": i,       # which slot's widgets this shell holds (identity at build)
            "accent": QColor("#555555"),
            "active": False,
            "dimmed": True,
        })
        # MultitoonTab expects these registries populated by the layout.
        self._tab.toon_cards.append(cell)
        self._tab.ka_groups.append(ka_pill)
        return self._cells[-1]

    # ── Populate ───────────────────────────────────────────────────────────
    def populate(self):
        """Reparent the shared per-slot widgets into the pinwheel leaf
        layouts. Idempotent: only the leaf layouts are cleared + refilled."""
        clear_layout(self._status_host)
        self._status_host.addWidget(self._tab.service_status_bar)

        for i, cell in enumerate(self._cells):
            self._populate_cell(i, cell)

        # Hidden-but-alive shared widgets the pinwheel design omits (kept so
        # MultitoonTab's logic and hotkeys keep working): the CC/TTR chip, the
        # click-sync help affordance, and the profile/config row.
        for i in range(4):
            if i < len(self._tab.game_badges):
                self._tab.game_badges[i].hide()
            if i < len(self._tab.help_buttons):
                self._tab.help_buttons[i].setParent(self._cells[i]["cell"])
                self._tab.help_buttons[i].hide()
        for w in (
            getattr(self._tab, "config_label", None),
            getattr(self._tab, "profile_pills_label", None),
            getattr(self._tab, "profile_save_button", None),
        ):
            if w is not None:
                w.setParent(self)
                w.hide()
        for pill in getattr(self._tab, "profile_pills", []):
            pill.setParent(self)
            pill.hide()

        # populate() routed slot i -> cell i (identity); sync the permutation
        # bookkeeping so a later apply_cell_permutation re-routes from a clean
        # identity baseline (matters when re-populating after a prior permutation,
        # e.g. switching back from the full layout).
        self._slot_to_cell = [0, 1, 2, 3]
        for idx, cell in enumerate(self._cells):
            cell["content_slot"] = idx

        self._relayout_all()
        self._apply_initial_brands()

    def control_rects(self, cell_index: int) -> list:
        """Card-local QRects of the five interactive control widgets in the shell
        at *cell_index*.

        These are the only widgets that stay opaque + clickable in transparent
        peek mode (the toggles, the keep-alive pill as one unit, and the keyset
        selector). Coordinates are relative to the shell cell root at the current
        (framed 1.0) size; the overlay controller scales them by the overlay zoom.
        Skips any widget that is missing or zero-sized (defensive).

        *cell_index* is the SHELL index (the overlay surface_id / screen quadrant -
        the same index ``slot_widget`` hosts), NOT a logical slot. A shell holds
        the shared widgets of the slot routed into it by ``apply_cell_permutation``
        (recorded as ``content_slot``; identity for every contiguous arrangement),
        so the per-slot widgets (toggles, keyset) come from ``content_slot`` while
        the keep-alive pill is the shell's own. This MUST match what ``slot_widget``
        hosts for that surface, or the peek dim/click-through lands on the wrong
        widgets (the 2-toon permuted-cluster bug).
        """
        cell = self._cells[cell_index]
        root = cell["cell"]
        if root.layout() is not None:
            root.layout().activate()
        tab = self._tab
        s = cell.get("content_slot", cell_index)
        widgets = [
            tab.toon_buttons[s],
            tab.chat_buttons[s],
            tab.click_sync_buttons[s],
            cell["ka_pill"],
            tab.set_selectors[s],
        ]
        rects = []
        for w in widgets:
            if w is None:
                continue
            size = w.size()
            if size.width() <= 0 or size.height() <= 0:
                continue
            top_left = w.mapTo(root, QPoint(0, 0))
            rects.append(QRect(top_left, size))
        return rects

    def set_shell_extra_opacity(self, cell_index: int, bg_opacity: float,
                                portrait_opacity: float) -> None:
        """Set the EXTRA hover-peek translucency factors for the two extra-dimmed
        card elements of the shell at *cell_index* (the overlay surface_id, as in
        control_rects / slot_widget): the background FILL (*bg_opacity*) and the
        circular PORTRAIT - its frame ring AND the toon image (*portrait_opacity*).

        The overlay composites the whole card uniformly (controls, text) via the
        surface's set_content_opacity; these dim the background fill and the
        portrait FURTHER, each by its own factor, so they read as more
        see-through than the content (net = content * factor). Applied as each
        widget's own paint opacity (no overlay, so rounded controls keep their real
        shape with no opaque corners). The toon image is the slot ROUTED into this
        shell (content_slot). 1.0 = no extra dim."""
        cell = self._cells[cell_index]
        bg = cell.get("bg")
        if bg is not None:
            bg.set_peek_opacity(bg_opacity)
        frame = cell.get("portrait_frame")
        if frame is not None and hasattr(frame, "set_peek_opacity"):
            frame.set_peek_opacity(portrait_opacity)   # the circular frame
        s = cell.get("content_slot", cell_index)
        badge = self._tab.slot_badges[s] if s < len(self._tab.slot_badges) else None
        if badge is not None and hasattr(badge, "set_peek_opacity"):
            badge.set_peek_opacity(portrait_opacity)   # the toon image inside it

    def _populate_cell(self, i: int, cell: dict):
        tab = self._tab
        cfg = cell["cfg"]
        align = Qt.AlignRight if not cfg["left"] else Qt.AlignLeft

        # Portrait: host the shared portrait badge inside the ring frame.
        # (Its fixed size is set by _size_cell, from the current metrics.)
        badge = tab.slot_badges[i]
        badge.setMinimumSize(0, 0)
        badge.setParent(cell["portrait_frame"])
        badge.set_border_color(None)
        badge.show()

        # Status dot overlays the portrait's outer-bottom corner.
        _, status_dot = tab.toon_labels[i]
        status_dot.setParent(cell["portrait_frame"])

        # Toggle row: enable / chat / click-sync.
        for b in (tab.toon_buttons[i], tab.chat_buttons[i], tab.click_sync_buttons[i]):
            b.setText("")
        clear_layout(cell["toggle_row"])
        cell["toggle_row"].addWidget(tab.toon_buttons[i])
        cell["toggle_row"].addWidget(tab.chat_buttons[i])
        cell["toggle_row"].addWidget(tab.click_sync_buttons[i])
        cell["toggle_row"].addStretch(1)

        # Keep-alive pill leaf: lightning toggle + progress bar.
        ka_btn = tab.keep_alive_buttons[i]
        ka_bar = tab.ka_progress_bars[i]
        ka_bar.setMaximumWidth(16777215)
        clear_layout(cell["ka_lay"])
        cell["ka_lay"].addWidget(ka_btn)
        cell["ka_lay"].addWidget(ka_bar, 1)

        # Keyset stepper leaf (shared SetSelectorWidget).
        sel = tab.set_selectors[i]
        sel.setMinimumWidth(0)
        sel.setMaximumWidth(16777215)
        clear_layout(cell["sel_holder"])
        cell["sel_holder"].addWidget(sel)

        # Name leaf: name expands to the card's outer edge so it elides.
        name_label, _ = tab.toon_labels[i]
        name_label.setAlignment(align | Qt.AlignVCenter)
        clear_layout(cell["name_holder"])
        cell["name_holder"].addWidget(name_label, 1)

        # Stats leaf: laff + beans, aligned to the outer edge.
        for lbl in (tab.laff_labels[i], tab.bean_labels[i]):
            lbl.show()
        clear_layout(cell["stats_row"])
        if cfg["left"]:
            cell["stats_row"].addWidget(tab.laff_labels[i])
            cell["stats_row"].addWidget(tab.bean_labels[i])
            cell["stats_row"].addStretch(1)
        else:
            cell["stats_row"].addStretch(1)
            cell["stats_row"].addWidget(tab.laff_labels[i])
            cell["stats_row"].addWidget(tab.bean_labels[i])

        # Apply all metric-derived sizes/fonts/icons (defaults to scale 1.0).
        self._size_cell(i, cell)

    def apply_cell_permutation(self, slot_cells) -> None:
        """Route each slot's content into the shell of its 2x2 cluster cell.

        ``slot_cells[i]`` is the cell (0=TL, 1=TR, 2=BL, 3=BR) that should display
        slot i's content; it must be a length-4 bijection (unused slots map to the
        empty cells). The four shells never move or change shape - only which
        slot's shared widgets they hold. For the identity permutation (every
        contiguous window arrangement) this is a no-op; only non-contiguous
        arrangements (a vertical stack, a gapped L-shape) route content into a
        shell other than its native one. Idempotent.
        """
        perm = list(slot_cells)[:4]
        if len(perm) != 4 or sorted(perm) != [0, 1, 2, 3]:
            return  # ignore a malformed permutation rather than scramble the cards
        if perm == self._slot_to_cell:
            return  # unchanged -> nothing to re-route
        self._slot_to_cell = perm
        # Route slot s's shared widgets into shell perm[s]; record which slot each
        # shell now holds (content_slot) for the chrome/geometry helpers.
        for slot, cell_idx in enumerate(perm):
            cell = self._cells[cell_idx]
            cell["content_slot"] = slot
            self._populate_cell(slot, cell)
        # Re-render every slot's chrome onto its (new) shell, then reposition the
        # manually-placed body + status dot for the moved content.
        self._apply_initial_brands()
        self._relayout_all()

    def _size_cell(self, i: int, cell: dict) -> None:
        """Apply every metric-derived size / font / icon to slot `i`'s widgets
        from self._metrics. Idempotent: re-run by apply_metrics() at any scale,
        and once at the end of _populate_cell. Touches only the shared per-slot
        widgets that the pinwheel already owns + the cell's own chrome, never the
        structural layout nesting (so it is reparent-free)."""
        tab = self._tab
        m = self._metrics

        # Cell envelope + content padding + controls column width.
        cell["cell"].setMinimumSize(0, m.card_min_h)
        pad = m.card_pad
        cell["content"].setContentsMargins(pad, pad, pad, pad)
        cell["ctrl_wrap"].setFixedWidth(m.ctrl_w)

        # _CompactLayout-owned layout spacings that drive the card's proportions.
        # Scaled here so apply_metrics re-applies them (at scale 1.0 each equals
        # its build-time literal byte-for-byte). card_pad is handled above via
        # m.card_pad; the outer cluster margins live in apply_metrics; GLOW_ROOM
        # is intentionally NOT scaled (see its definition).
        # DEFERRED to the scale-fidelity polish follow-up (NOT scaled here): the
        # status-dot halo/pulse-glow offsets + cutout ring-width
        # (utils/shared_widgets.py), the KA long-press charge-arc margin/pen, and
        # the portrait-badge inset/border/pattern-tile/fallback-fonts
        # (tabs/multitoon/_tab.py).
        cell["content"].setSpacing(m.icon_px(12))
        cell["toggle_row"].setSpacing(m.icon_px(9))
        cell["ctrl_col"].setSpacing(m.icon_px(10))
        cell["body_row"].setSpacing(m.icon_px(10))
        cell["stats_row"].setSpacing(m.icon_px(16))
        cell["meta_col"].setSpacing(m.icon_px(5))

        # Painted body radii/border + portrait ring scale.
        cell["bg"].apply_metrics(m)
        cell["portrait_frame"].apply_metrics(m)

        # Portrait badge fits inside the (now-resized) ring frame.
        badge = tab.slot_badges[i]
        hx, hy, hw, hh = cell["portrait_frame"].host_geometry()
        badge.setFixedSize(hw, hh)
        badge.move(hx, hy)

        # Status dot diameter.
        _, status_dot = tab.toon_labels[i]
        status_dot.set_size(m.icon_px(34))

        # Toggle buttons + their glyph icons.
        ts = QSize(m.icon_px(17), m.icon_px(17))
        for b in (tab.toon_buttons[i], tab.chat_buttons[i], tab.click_sync_buttons[i]):
            b.setFixedSize(m.toggle_w, m.toggle_h)
            b.setIconSize(ts)

        # Keep-alive pill height + lightning dot + progress bar.
        cell["ka_pill"].setFixedHeight(m.ka_pill_h)
        # KA pill's own internal margins + spacing (layout-owned literals: 5/11
        # margins, 9 spacing at scale 1.0) scale with the metric so the pill's
        # interior keeps its proportions when rescaled.
        cell["ka_lay"].setContentsMargins(m.icon_px(5), 0, m.icon_px(11), 0)
        cell["ka_lay"].setSpacing(m.icon_px(9))
        # Restyle the pill border-radius so it tracks the new height (stays a
        # true capsule at non-1.0 scale; the radius is derived from m.ka_pill_h).
        self._style_ka_pill(i)
        ka_btn = tab.keep_alive_buttons[i]
        ka_btn.setFixedSize(m.ka_dot, m.ka_dot)
        ka_btn.setIconSize(QSize(m.icon_px(13), m.icon_px(13)))
        ka_bar = tab.ka_progress_bars[i]
        ka_bar.setFixedHeight(m.icon_px(9))
        ka_bar.setMinimumWidth(m.icon_px(40))

        # Keyset stepper height + its internal paint scale.
        sel = tab.set_selectors[i]
        sel.setFixedHeight(m.keyset_h)
        if hasattr(sel, "set_paint_scale"):
            sel.set_paint_scale(m.scale)

        # Name font.
        name_label, _ = tab.toon_labels[i]
        name_font = QFont()
        name_font.setPixelSize(round(m.font_pt(23)))
        name_font.setBold(True)
        name_label.setFont(name_font)

        # Stats fonts + glyph icons + height cap.
        stat_size = round(m.font_pt(15))
        stat_icon = QSize(m.icon_px(16), m.icon_px(16))
        stat_h = m.icon_px(22)
        for lbl in (tab.laff_labels[i], tab.bean_labels[i]):
            lbl.setFixedHeight(stat_h)
            lbl.setIconSize(stat_icon)
            stat_font = QFont()
            stat_font.setPixelSize(stat_size)
            stat_font.setWeight(QFont.DemiBold)
            lbl.setFont(stat_font)

    # ── Brand / per-slot render ──────────────────────────────────────────────
    def set_card_brand(self, i: int, game: str | None, enabled: bool = False) -> None:
        """Render slot `i` end to end: card chrome, the five controls,
        portrait, name/stats, dim/glow. `enabled` already folds in
        service_running (MultitoonTab passes enabled & service_running)."""
        if i >= len(self._cells):
            return
        from utils.theme_manager import get_theme_colors, resolve_theme
        from utils.toon_customization_resolve import resolve_accent
        c = get_theme_colors(resolve_theme(self._tab.settings_manager) == "dark")
        # Slot i's content lives in shell _slot_to_cell[i] (identity unless a
        # non-contiguous arrangement routed it elsewhere). Chrome for this slot
        # goes onto that shell; the shared per-slot widgets stay indexed by i.
        cell_idx = self._slot_to_cell[i]
        cell = self._cells[cell_idx]
        tab = self._tab

        wids = tab.window_manager.ttr_window_ids if hasattr(tab, "window_manager") else []
        window_available = i < len(wids)
        is_toon = game in ("cc", "ttr")

        # Accent: per-toon override, else the game brand colour.
        # Body-fill override: separate `body` key when set, else None (the
        # card background falls back to the accent for the fill gradient).
        if game == "cc":
            entry = self._entry(i, "cc")
            accent = resolve_accent(entry, QColor(c["game_pill_cc"]))
        elif game == "ttr":
            entry = self._entry(i, "ttr")
            accent = resolve_accent(entry, QColor(c["game_pill_ttr"]))
        else:
            entry = {}
            accent = QColor(c["border_light"])
        from utils.toon_customization_resolve import resolve_body
        body_override = resolve_body(entry)

        active = bool(enabled) and window_available and is_toon
        cell["dimmed"] = not active
        cell["accent"] = QColor(accent)
        cell["active"] = active

        cell["bg"].configure(accent, dimmed=not active, body=body_override)
        cell["portrait_frame"].configure(accent, dimmed=not active)
        self._apply_cell_effects(cell, accent, active)
        self._refresh_glow()

        # Layout-owned control chrome: the KA pill container + the keyset
        # stepper colour. The five toggle buttons themselves are styled by
        # MultitoonTab (single style-writer per control); the cell's dim
        # effect desaturates them in place when the card is off/stopped.
        self._style_ka_pill(cell_idx)
        self._style_keyset(i)

        # Portrait background + status dot.
        tab.slot_badges[i].set_border_color(None)
        tab.slot_badges[i].set_colors("#101010", "#ffffff")
        status_dot = tab.toon_labels[i][1]
        if active:
            status_dot.set_cutout_border(darken_rgb(accent, 0.21).name(), width=3.0)
            status_dot.set_state("active", "Connected")
            status_dot.show()
        else:
            status_dot.hide()

        # Name + stats colour.
        name_label = tab.toon_labels[i][0]
        name_label.setStyleSheet(
            "background: transparent; border: none; color: #ffffff;"
        )
        stat_style = (
            "background: transparent; border: none; text-align: left; "
            "padding: 0; color: rgba(255,255,255,0.9); font-weight: 600;"
        )
        tab.laff_labels[i].setStyleSheet(stat_style)
        tab.bean_labels[i].setStyleSheet(stat_style)

        self._position_status_dot(cell)
        self._refresh_emblem()

    def _apply_cell_effects(self, cell: dict, accent: QColor, active: bool) -> None:
        """Dimmed cards get a painted grey wash (proxy-safe), not a live
        QGraphicsColorizeEffect, which renders corrupt inside a QGraphicsProxyWidget."""
        cell_w = cell["cell"]
        if cell_w.graphicsEffect() is not None:
            cell_w.setGraphicsEffect(None)  # purge any legacy effect
        dim = cell.get("dim")
        if dim is None:
            from tabs.multitoon._card_dim_overlay import CardDimOverlay
            dim = CardDimOverlay(cell_w)
            cell["dim"] = dim
        from utils.effects_flags import effects_disabled
        dim.set_dimmed(bool(not active and not effects_disabled()))

    # ── Control chrome owned by the layout ───────────────────────────────────
    def _style_ka_pill(self, cell_idx: int) -> None:
        """Style the keep-alive pill of SHELL `cell_idx` (a layout-owned container;
        the lightning toggle + progress bar inside it are styled by MultitoonTab).
        Indexed by shell, not slot: the pill is part of the shell structure
        (objectName ka_pill_{cell_idx}), so content routed into this shell uses it."""
        cell = self._cells[cell_idx]
        ka_pill = cell.get("ka_pill")
        if ka_pill is not None:
            # Radius tracks the (scaled) pill height so the capsule stays a true
            # pill at every scale (1.0: round(38/2)==19, unchanged).
            radius = round(self._metrics.ka_pill_h / 2)
            ka_pill.setStyleSheet(
                f"QFrame#ka_pill_{cell_idx} {{ background: rgba(0,0,0,0.24);"
                f" border: 1px solid rgba(0,0,0,0.30); border-radius: {radius}px; }}"
            )

    def _style_keyset(self, i: int) -> None:
        sel = self._tab.set_selectors[i]
        # SetSelectorWidget already renders a ‹ KeysetName › stepper coloured
        # by the movement-set palette; just make sure it repaints.
        sel.update()

    # ── Misc state helpers ───────────────────────────────────────────────────
    def _entry(self, i: int, game: str) -> dict:
        tab = self._tab
        name = tab.toon_names[i] if i < len(tab.toon_names) else None
        if name and tab.customizations is not None:
            return tab.customizations.get(game, name)
        return {}

    # ── Theme ────────────────────────────────────────────────────────────────
    def apply_theme(self, c: dict) -> None:
        if self._emblem is not None:
            broadcasting = bool(getattr(self._tab, "service_running", False))
            self._emblem.configure(broadcasting, c["bg_app"], c["accent_blue_btn"])
        self._apply_initial_brands()

    def _apply_initial_brands(self) -> None:
        for i in range(min(4, len(self._cells))):
            game = self._tab.slot_badges[i].game if i < len(self._tab.slot_badges) else None
            enabled = bool(
                i < len(self._tab.enabled_toons)
                and self._tab.enabled_toons[i]
                and getattr(self._tab, "service_running", False)
            )
            self.set_card_brand(i, game, enabled=enabled)
        self._refresh_emblem()

    def _refresh_emblem(self) -> None:
        if self._emblem is None:
            return
        from utils.theme_manager import get_theme_colors, resolve_theme
        c = get_theme_colors(resolve_theme(self._tab.settings_manager) == "dark")
        broadcasting = bool(getattr(self._tab, "service_running", False))
        self._emblem.configure(broadcasting, c["bg_app"], c["accent_blue_btn"])

    # ── Keep-alive collapse (master switch) ──────────────────────────────────
    def _collapsed_ka_group_width(self, i: int) -> int:
        """Width the ka_group occupies when keep-alive is collapsed.
        The pinwheel layout hides the ka_pill rather than width-pinning it,
        so this is never called in practice; it satisfies the MultitoonTab
        interface shared with the full layout."""
        cell = self._cells[self._slot_to_cell[i]] if i < len(self._cells) else {}
        pill = cell.get("ka_pill")
        return pill.minimumSizeHint().width() if pill is not None else 0

    def _set_keep_alive_collapsed(self, collapsed: bool) -> None:
        for cell in self._cells:
            pill = cell.get("ka_pill")
            if pill is not None:
                pill.setVisible(not collapsed)

    def _animate_keep_alive_visibility(self, target_visible: bool) -> None:
        # Snap visibility (the design's fade is cosmetic; snapping avoids the
        # offscreen QGraphicsOpacityEffect crash path).
        self._set_keep_alive_collapsed(not target_visible)

    # ── Scale (transparent-mode resize) ──────────────────────────────────────
    def apply_metrics(self, metrics) -> None:
        """Recompute the whole card cluster's geometry from a single CardMetrics
        at ANY scale (0.5-1.75), WITHOUT rebuilding the widget tree: mutate the
        existing widgets' sizes/fonts/icons + the painted body-path radii, then
        repaint. The structural nesting is never re-parented. Scale 1.0
        reproduces the framed appearance byte-for-byte. Idempotent; safe to call
        repeatedly (e.g. by the overlay controller across surfaces, Task 4.2)."""
        self._metrics = metrics
        # Inter-card grid spacing (the GLOW_ROOM grid margin is fixed by design;
        # see its definition for why it is not scaled).
        if self._grid is not None:
            self._grid.setSpacing(metrics.grid_gap)
        # Status bar's top margin scales too (it is a layout on the whole
        # cluster, not per-cell, so it lives here rather than in _size_cell).
        if getattr(self, "_status_host", None) is not None:
            self._status_host.setContentsMargins(0, metrics.status_top_margin, 0, 0)
        # Outer cluster content margins (the _CompactLayout's own QVBoxLayout):
        # a layout-owned literal (8,6,8,8 at scale 1.0) that affects the cluster
        # proportions, so it scales with the metric too.
        if self._outer is not None:
            self._outer.setContentsMargins(
                metrics.icon_px(8), metrics.icon_px(6),
                metrics.icon_px(8), metrics.icon_px(8),
            )
        # Per-cell sizes/fonts/icons + painted radii + portrait ring.
        for i, cell in enumerate(self._cells):
            self._size_cell(i, cell)
        # Central emblem disc + glow halo softness.
        if self._emblem is not None:
            self._emblem.apply_metrics(metrics)
        if self._glow is not None:
            self._glow.set_blur(metrics.glow_blur)
        # Force a synchronous layout pass before repositioning: changing fixed
        # sizes / grid spacing only POSTS a layout request, so without this the
        # manual bg/glow/status-dot positioning in _relayout_all could read
        # stale cell geometry. Makes apply_metrics self-contained (the overlay
        # controller, Task 4.2, can rely on geometry being current right after).
        if self._grid is not None:
            self._grid.activate()
        # Reposition the painted backgrounds, status dots, glow + emblem at the
        # new sizes, then repaint everything.
        self._relayout_all()
        self.update()

    # ── No-ops / lifecycle for the MultitoonTab contract ─────────────────────
    def deactivate(self) -> None:
        if self._emblem is not None:
            self._emblem.stop()

    def _position_cards(self) -> None:  # full-layout shim; unused here
        pass

    # ── Geometry positioning ─────────────────────────────────────────────────
    def _relayout_all(self) -> None:
        for cell in self._cells:
            self._position_cell_bg(cell)
            self._position_status_dot(cell)
        if self._glow is not None and self._grid_host is not None:
            self._glow.setGeometry(0, 0, self._grid_host.width(), self._grid_host.height())
            self._glow.lower()
        self._refresh_glow()
        self._position_emblem()

    def _refresh_glow(self) -> None:
        """Feed the glow layer each lit card's body rect (in grid-host coords)
        + accent. Dimmed/empty cards contribute no glow."""
        if self._glow is None:
            return
        specs = []
        for cell in self._cells:
            if not cell.get("active"):
                continue
            geo = cell["cell"].geometry()   # cells live in the grid host
            specs.append({
                "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height(),
                "cutout": cell["cfg"]["cutout"], "accent": QColor(cell["accent"]),
                "radius": self._metrics.card_radius,
                "cutout_r": self._metrics.cutout_r,
            })
        self._glow.set_cards(specs)

    def _position_cell_bg(self, cell: dict) -> None:
        c = cell["cell"]
        w, h = c.width(), c.height()
        cell["glow_host"].setGeometry(0, 0, w, h)
        cell["bg"].setGeometry(0, 0, w, h)
        cell["glow_host"].lower()

    def _position_status_dot(self, cell: dict) -> None:
        frame = cell["portrait_frame"]
        dot = None
        # The dot in this shell belongs to the slot whose content is routed here
        # (content_slot), NOT the shell's own index.
        idx = cell.get("content_slot", self._cells.index(cell))
        if idx < len(self._tab.toon_labels):
            dot = self._tab.toon_labels[idx][1]
        if dot is None or dot.parentWidget() is not frame:
            return
        # Bottom-right inner corner of the portrait circle.
        portrait = self._metrics.portrait
        d = dot.width()
        off = int(portrait * 0.5 + (portrait * 0.5) * 0.70) - d // 2
        dot.move(off, off)
        dot.raise_()

    def _position_emblem(self) -> None:
        if self._emblem is None or self._grid_host is None:
            return
        gx = self._grid_host.width() / 2.0
        gy = self._grid_host.height() / 2.0
        s = self._emblem.width()
        self._emblem.move(int(gx - s / 2.0), int(gy - s / 2.0))
        self._emblem.raise_()

    # ── Overlay / transparent-mode reparent accessors (Task 4.1b) ────────────
    def slot_widget(self, slot: int) -> QWidget:
        """The grid-managed card QFrame for `slot` (0-3) - the unit the overlay
        controller hosts into a CardSurface on transparent-mode enter and
        restores to the grid on leave. Pairs with capture_slot/restore_slot."""
        return self._cells[slot]["cell"]

    def emblem_widget(self) -> "_Emblem | None":
        """The manually-positioned, raised emblem widget - hosted into the
        EmblemSurface on enter and restored manual + raised on leave."""
        return self._emblem

    def card_size(self) -> tuple[int, int]:
        """The scaled (width, height) every card overlay surface must use: the MAX
        cell sizeHint across ALL FOUR slots at the CURRENT metrics. The cluster is
        a symmetric pinwheel (uniform surface size), so every surface is sized to
        fit the WIDEST/TALLEST card. The cards are NOT identical in width - an
        eliding name/keyset label reports its full text width as its sizeHint, so
        a slot with a long toon name is wider than another; sizing all surfaces to
        one slot would clamp/clip the wider slots. Used by the overlay controller
        (Task 4.2) to reconcile each surface rect with the real scaled card,
        resolving the CardMetrics(round)-vs-pinwheel_rects(int) 1px discrepancy in
        favour of the live widget. Returns (0, 0) before the cells exist."""
        if not self._cells:
            return (0, 0)
        w = h = 0
        for cell_dict in self._cells:
            cell = cell_dict["cell"]
            # In overlay mode the cell is hosted OUTSIDE the grid (in its surface),
            # so apply_metrics' grid.activate() cannot refresh the cell's own
            # content-layout sizeHint. Invalidate+activate here so the read
            # reflects the latest metrics synchronously (no event-loop tick).
            lay = cell.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            hint = cell.sizeHint()
            w = max(w, hint.width())
            h = max(h, hint.height())
        return (w, h)

    def emblem_size(self) -> int:
        """The scaled emblem surface side in px - the FULL emblem widget extent
        (disc diameter + ring-margin chrome on both sides), read from the live
        fixed-size emblem widget so the emblem surface fits it WITHOUT clipping.
        The visible disc (CardMetrics.emblem) is centered inside this square; the
        ring margin holds the broadcast pulse ring + glow. The widget is a fixed
        square, so width() is authoritative (analogous to card_size() reading the
        cell sizeHint). Returns 0 when there is no emblem."""
        if self._emblem is None:
            return 0
        return self._emblem.width()

    def overlay_base_card_size(self) -> tuple[int, int]:
        """The card's 1.0 size for the overlay proxy: the uniform card sizeHint
        (max width AND max height across the four cells). The proxied card is fixed
        to this size so its content FITS exactly, and the per-card view transform
        then scales the whole card as one unit.

        This MUST be the full sizeHint, NOT card_min_h for the height: a cell's real
        content minimum (minimumSizeHint) exceeds card_min_h (which is only a design
        floor), so sizing the window to card_min_h left the content taller than the
        window and the QGraphicsView scrolled the oversized scene (cards "did not
        fit")."""
        return self.card_size()

    def overlay_relayout_card(self, card_widget) -> None:
        """Re-place a single card's manually-positioned body + status dot to the
        cell's CURRENT size. The overlay setFixedSizes the cell when hosting it, but
        the parent layout's resizeEvent (which normally drives _relayout_all) never
        fires for a cell reparented out into a surface, so the body must be re-placed
        explicitly here - else it stays at the framed size and the card content
        spills past the painted body (the "right side cut off")."""
        for cell in self._cells:
            if cell["cell"] is card_widget:
                self._position_cell_bg(cell)
                self._position_status_dot(cell)
                return

    def scale_emblem(self, scale: float) -> None:
        """Scale only the emblem disc to `scale` (the overlay scales cards via a
        view transform, but the emblem stays a single painted widget that scales
        cleanly via metrics and never floats). emblem_size() reflects the new
        extent afterward."""
        from utils.overlay.card_metrics import CardMetrics
        if self._emblem is not None:
            self._emblem.apply_metrics(CardMetrics(scale))

    def card_accents(self) -> list:
        """Per-slot accent QColor (slots 0-3) for the transparent-mode overlay
        glow. Mirrors the framed _GlowLayer's per-cell accent so the overlay can
        paint the same soft halo behind its card surfaces. Falls back to the
        canonical idle grey when a cell has no accent yet."""
        from PySide6.QtGui import QColor
        out = []
        for i in range(4):
            cell = self._cells[i] if i < len(self._cells) else None
            accent = cell.get("accent") if cell else None
            out.append(QColor(accent) if accent is not None else QColor("#555555"))
        return out

    # ── Overlay / transparent-mode geometry accessors ───────────────────────
    def card_body_paths(self):
        """Per-card painted body paths (rounded rect minus concave bite), in
        grid-host coordinates. Used by the overlay controller to build the
        X11 ShapeInput input region. Pure read — no behavior change."""
        from PySide6.QtGui import QTransform
        paths = []
        for cell in self._cells:
            frame = cell["cell"]           # QFrame — the grid child
            cutout = cell["cfg"]["cutout"] # "tl"/"tr"/"bl"/"br"
            geo = frame.geometry()         # position within _grid_host
            local = _card_body_path(
                geo.width(), geo.height(), cutout,
                self._metrics.card_radius, self._metrics.cutout_r,
            )
            paths.append(local * QTransform().translate(geo.x(), geo.y()))
        return paths

    def emblem_path(self):
        """Emblem disc path in grid-host coordinates. Used alongside
        card_body_paths() to compose the full input region. Pure read."""
        from PySide6.QtGui import QPainterPath
        from PySide6.QtCore import QPointF
        p = QPainterPath()
        if self._emblem is not None:
            geo = self._emblem.geometry()
            cx = geo.x() + geo.width() / 2.0
            cy = geo.y() + geo.height() / 2.0
            r = self._metrics.emblem / 2.0
            p.addEllipse(QPointF(cx, cy), r, r)
        return p

    # ── Slot save/restore (foundation for the Task 4.1b reparent) ────────────
    @staticmethod
    def _is_topmost(widget: QWidget) -> bool:
        """True if `widget` is the top-most among its parent's sibling widgets.
        Qt keeps sibling widgets in stacking order in the parent's children
        list, so the last QWidget child is the raised one."""
        parent = widget.parentWidget()
        if parent is None:
            return False
        siblings = [c for c in parent.children() if isinstance(c, QWidget)]
        return bool(siblings) and siblings[-1] is widget

    def capture_slot(self, widget: QWidget) -> SlotRecord:
        """Snapshot `widget`'s exact place so restore_slot() can reinsert it
        identically. Round-trips ANY of the pinwheel widgets - the 4 card
        QFrames (grid-managed) and the emblem (manually positioned + raised).
        The grid-vs-manual case is detected by membership in self._grid.

        Captures, for a grid-managed widget: its grid + position
        (row, col, rowSpan, colSpan via getItemPosition) + the layout-item
        alignment, plus visibility + a copied size policy. For the manually
        positioned emblem: its parent + geometry/pos + visibility + whether it
        is raised above the cards, plus a copied size policy.

        Scope (for Task 4.1b): this snapshot is PLACEMENT-only. It does NOT
        capture interactivity (WA_TransparentForMouseEvents / the emblem's
        set_interactive state) or attached QGraphicsEffects - those ride on the
        widget across a reparent, and the emblem's interactivity toggle is
        controller state the caller manages separately."""
        parent = widget.parentWidget()
        # QSizePolicy is a value type; copy it so a later mutation of the live
        # widget's policy can't corrupt the captured snapshot.
        size_policy = QSizePolicy(widget.sizePolicy())
        # Capture the INTRINSIC hidden flag, not isVisible(): isVisible() is
        # ancestor-dependent (False whenever any ancestor is hidden - e.g. the
        # Multitoon tab page isn't current, or the main window is minimized, which
        # is exactly the transparent-mode case). Pairing isVisible() with
        # setVisible() on restore would explicitly hide a card that was only
        # ancestor-hidden, leaving it stuck invisible. `not isHidden()` is the
        # intrinsic state and is symmetric with setVisible().
        visible = not widget.isHidden()

        grid = self._grid
        index = grid.indexOf(widget) if grid is not None else -1
        if index >= 0:
            row, col, row_span, col_span = grid.getItemPosition(index)
            item = grid.itemAt(index)
            alignment = item.alignment() if item is not None else Qt.Alignment()
            return SlotRecord(
                widget=widget, kind="grid", parent=parent, visible=visible,
                size_policy=size_policy, grid=grid, row=row, col=col,
                row_span=row_span, col_span=col_span, alignment=alignment,
            )

        # Manual case (the emblem): geometry + z-order, no layout.
        return SlotRecord(
            widget=widget, kind="manual", parent=parent, visible=visible,
            size_policy=size_policy,
            geometry=QRect(widget.geometry()), pos=QPoint(widget.pos()),
            raised=self._is_topmost(widget),
        )

    def restore_slot(self, record: SlotRecord) -> None:
        """Reinsert the widget captured by capture_slot() into its EXACT place.
        Symmetric with capture_slot: capture(w) -> (reparent w away,
        e.g. w.setParent(None)) -> restore leaves w exactly where it started.
        Calling restore without reparenting away first is a safe near-no-op:
        the widget is not duplicated in the grid and nothing errors."""
        widget = record.widget
        if record.kind == "grid":
            grid = record.grid
            if grid is not None:
                # Idempotent: drop any existing layout item for this widget
                # first so a restore-without-reparent can't create a duplicate
                # grid item (removeWidget is a no-op when it isn't present).
                grid.removeWidget(widget)
                grid.addWidget(
                    widget, record.row, record.col,
                    record.row_span, record.col_span, record.alignment,
                )
            widget.setSizePolicy(record.size_policy)
            widget.setVisible(record.visible)
            return

        # Manual case (the emblem): re-parent, restore geometry, restack.
        if record.parent is not None:
            widget.setParent(record.parent)
        if record.geometry is not None:
            widget.setGeometry(record.geometry)
        elif record.pos is not None:
            widget.move(record.pos)
        widget.setSizePolicy(record.size_policy)
        widget.setVisible(record.visible)
        if record.raised:
            # Keep the emblem above the cards (it nests in the carved centre).
            widget.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout_all()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_all()

    def eventFilter(self, obj, event):
        # Re-place a cell's manually-positioned body + status dot whenever the cell
        # ITSELF resizes (e.g. setFixedSize when hosted in a transparent-mode
        # surface), so they track the cell even when it is reparented out of this
        # layout and this widget's own resizeEvent never fires for it.
        if event.type() == QEvent.Resize:
            for cell in self._cells:
                if cell["cell"] is obj:
                    self._position_cell_bg(cell)
                    self._position_status_dot(cell)
                    break
        return super().eventFilter(obj, event)
