"""The painted strip: one row of blocks for one game window.

The widget only paints a StripModel and reports what was pressed. It keeps
no toon state of its own, takes no focus and has no background, so it can
sit in a translucent, click-through surface.
"""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal,
                            QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from utils.asset_paths import asset_path
from utils.strips import layout as L
from utils.strips import paint, tokens
from utils.strips.model import StripModel

# Room around the row for the Neon halos (3 sigma of the widest, 9 px blur).
# Kept in both looks so switching look never moves the blocks.
MARGIN = 14.0

# State changes cross-fade: fills and glows in 140 ms, the dim of a disabled
# toon in 200 ms. Nothing moves, so there is nothing to animate when the
# layout itself changes; and nothing at all under reduced motion.
FADE_MS = 140
DIM_FADE_MS = 200


def _motion_reduced() -> bool:
    try:
        from utils import motion
        return bool(motion.is_reduced())
    except Exception:
        return False


_home_icons: dict[int, QPixmap] = {}


def _home_icon(device_px: int) -> QPixmap | None:
    """The app icon, smooth-scaled once per device size."""
    device_px = max(1, int(device_px))
    hit = _home_icons.get(device_px)
    if hit is not None:
        return hit
    source = QPixmap(asset_path("multitool.png"))
    if source.isNull():
        return None
    pm = source.scaled(device_px, device_px, Qt.KeepAspectRatioByExpanding,
                       Qt.SmoothTransformation)
    _home_icons[device_px] = pm
    return pm


class StripWidget(QWidget):
    clicked = Signal(str, int)             # block kind, keyset number (0 if none)
    context_requested = Signal(str, int)   # right-click on a block
    hover_changed = Signal(str, int)       # "" when the pointer is on no block

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = StripModel()
        self._style = tokens.NEON_STYLE
        self._painter = paint.painter_for(self._style)
        self._scale = 1.0
        self._client_width: float | None = None
        self._layout = None
        self._hover: tuple[str, int] | None = None
        self._pressed: tuple[str, int] | None = None
        self._reduced_fn = _motion_reduced
        self._fade_from: QPixmap | None = None
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.valueChanged.connect(lambda _v: self.update())
        self._fade.finished.connect(self._end_fade)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._relayout()

    # -- inputs -------------------------------------------------------------

    def model(self) -> StripModel:
        return self._model

    def set_model(self, model: StripModel) -> None:
        if model == self._model and model.portrait is self._model.portrait:
            return
        old, old_layout = self._model, self._layout
        before = self._snapshot() if self._may_animate() else None
        self._model = model
        self._relayout()
        if before is not None and self._layout.blocks == old_layout.blocks:
            self._fade_from = before
            self._fade.stop()
            self._fade.setDuration(DIM_FADE_MS if old.dimmed != model.dimmed else FADE_MS)
            self._fade.start()
        else:
            self._end_fade()

    def set_reduced_motion_fn(self, fn) -> None:
        """Replace the reduced-motion test (tests; a host with its own rule)."""
        self._reduced_fn = fn

    def is_fading(self) -> bool:
        return self._fade_from is not None

    def _may_animate(self) -> bool:
        if not self.isVisible() or self.width() <= 0:
            return False
        try:
            return not self._reduced_fn()
        except Exception:
            return True

    def _end_fade(self) -> None:
        if self._fade_from is not None:
            self._fade.stop()
            self._fade_from = None
            self.update()

    def _snapshot(self) -> QPixmap:
        """The strip as it is painted now, at device resolution."""
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(max(1, int(round(self.width() * dpr))),
                     max(1, int(round(self.height() * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        self.render_strip(p)
        p.end()
        return pm

    def style_name(self) -> str:
        return self._style.name

    def set_style(self, name: str) -> None:
        style = tokens.style_for(name)
        if style is self._style:
            return
        self._style = style
        self._painter = paint.painter_for(style)
        self._relayout()

    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        """Multiplier on every metric. The surface passes the inverse of the
        app's UI scale so the strip is true-size on the game window."""
        scale = float(scale) if scale and scale > 0 else 1.0
        if abs(scale - self._scale) < 1e-6:
            return
        self._scale = scale
        self._relayout()

    def set_client_width(self, width: float | None) -> None:
        """Width of the game window's client area in strip design px; drives
        the narrow-window collapse. None lays the strip out in full."""
        if width == self._client_width:
            return
        self._client_width = width
        self._relayout()

    # -- geometry -----------------------------------------------------------

    def strip_layout(self) -> L.StripLayout:
        return self._layout

    def _relayout(self) -> None:
        self._layout = L.fit_strip(
            self._model, self._style,
            lambda text: paint.measure_name(self._style, text),
            self._client_width)
        hint = self.sizeHint()
        if self.size() != hint:
            self.setFixedSize(hint)
        self.update()

    def sizeHint(self) -> QSize:
        k = self._scale
        return QSize(int(round((self._layout.width + 2 * MARGIN) * k)),
                     int(round((self._layout.height + 2 * MARGIN) * k)))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def row_offset(self) -> QPointF:
        """Widget-local position of the row's top-left corner."""
        return QPointF(MARGIN * self._scale, MARGIN * self._scale)

    def row_size(self) -> QSize:
        """Size of the row itself (halo margins excluded), widget px."""
        k = self._scale
        return QSize(int(round(self._layout.width * k)),
                     int(round(self._layout.height * k)))

    def _to_widget(self, rect: QRectF) -> QRectF:
        k = self._scale
        return QRectF((rect.x() + MARGIN) * k, (rect.y() + MARGIN) * k,
                      rect.width() * k, rect.height() * k)

    def block_rect(self, kind: str, number: int = 0) -> QRectF | None:
        """A block's rectangle in widget coordinates, or None."""
        block = self._layout.find(kind, number)
        return None if block is None else self._to_widget(block.rect)

    def identity_rect(self) -> QRectF:
        return self._to_widget(self._layout.identity_rect())

    def input_rects(self) -> list[QRect]:
        """Widget-local rectangles that take the pointer: the union of these
        is the surface's input region. Everything else is click-through."""
        out = []
        for b in self._layout.blocks:
            if b.kind in L.INTERACTIVE:
                out.append(self._to_widget(b.rect).toAlignedRect())
        return out

    def _hit(self, pos) -> L.Block | None:
        k = self._scale
        return self._layout.hit(pos.x() / k - MARGIN, pos.y() / k - MARGIN)

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        old = self._fade_from
        if old is None or old.size() != self._snapshot_size():
            self.render_strip(p)
        else:
            # A true cross-dissolve: old * (1 - t) + new * t, built on its own
            # layer so translucent parts neither dip nor double up.
            t = float(self._fade.currentValue() or 0.0)
            frame = self._weighted(old, 1.0 - t)
            fp = QPainter(frame)
            # Plus at full opacity: with a painter opacity Qt blends the sum
            # back toward the destination and the result comes out thin.
            fp.setCompositionMode(QPainter.CompositionMode_Plus)
            fp.drawPixmap(0, 0, self._weighted(self._snapshot(), t))
            fp.end()
            p.drawPixmap(0, 0, frame)
        p.end()

    @staticmethod
    def _weighted(pixmap: QPixmap, weight: float) -> QPixmap:
        """`pixmap` scaled by `weight` in every channel, alpha included."""
        out = QPixmap(pixmap.size())
        out.setDevicePixelRatio(pixmap.devicePixelRatio())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setOpacity(max(0.0, min(1.0, weight)))
        p.drawPixmap(0, 0, pixmap)
        p.end()
        return out

    def _snapshot_size(self) -> QSize:
        dpr = self.devicePixelRatioF() or 1.0
        return QSize(max(1, int(round(self.width() * dpr))),
                     max(1, int(round(self.height() * dpr))))

    def render_strip(self, p: QPainter) -> None:
        """Paint the strip with the painter's origin at the widget's."""
        m, s, lay, pt = self._model, self._style, self._layout, self._painter
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(self._scale, self._scale)
        p.translate(MARGIN, MARGIN)

        dim = m.dimmed
        tone = (tokens.css_saturate_brightness
                if dim and s.is_neon else paint.identity)
        portrait = lay.find(L.PORTRAIT)
        name = lay.find(L.NAME)

        # Pass 1: halos, under every block.
        for b in lay.blocks:
            if b.kind == L.HOME:
                pt.glow_home(p, b.rect, m.home_open)
            elif b.kind == L.SEPARATOR:
                pt.glow_separator(p, b.rect)
            elif b.kind in (L.KEEP_ALIVE, L.CLICK_SYNC):
                on = bool(m.keep_alive) if b.kind == L.KEEP_ALIVE else m.click_sync_lit
                pt.glow_tool(p, b.rect, pt.tool_colour(b.kind, on), on, tone)
            elif b.kind == L.KEYSET:
                pt.glow_tool(p, b.rect, tokens.set_color(b.number),
                             b.number == m.active, tone)
            elif b.kind == L.ENABLE:
                pt.glow_tool(p, b.rect, pt.tool_colour(b.kind, m.enabled), m.enabled)
        pt.glow_identity(p, portrait.rect, name.rect if name else None,
                         m.accent, dim)

        # Pass 2: identity. The portrait sits on top of the plate's tucked end.
        if name is not None:
            pt.name(p, name.rect, m.name, m.accent, dim)
        pt.portrait(p, portrait.rect, m.accent, m.species, m.portrait, dim)

        # Pass 3: tools and keysets, the part that dims with the toon.
        if dim and not s.is_neon:
            self._paint_flat_dimmed(p)
        else:
            self._paint_dimmable(p, tone)

        # Pass 4: what never dims.
        for b in lay.blocks:
            if b.kind == L.SEPARATOR:
                pt.separator(p, b.rect)
            elif b.kind == L.ENABLE:
                pt.tool(p, self._nudged(b), b.kind, m.enabled,
                        hover=self._hover == b.key)
            elif b.kind == L.HOME:
                size = int(round(b.rect.width() * paint._device_scale(p)))
                pt.home(p, self._nudged(b), _home_icon(size), m.home_open,
                        not m.running)
        p.restore()

    def _nudged(self, block: L.Block) -> QRectF:
        """A pressed block sits one pixel lower."""
        if self._pressed == block.key:
            return block.rect.translated(0.0, 1.0)
        return block.rect

    def _paint_dimmable(self, p: QPainter, tone) -> None:
        m, pt = self._model, self._painter
        for b in self._layout.blocks:
            hover = self._hover == b.key
            if b.kind == L.KEEP_ALIVE:
                pt.tool(p, self._nudged(b), b.kind, bool(m.keep_alive), tone, hover)
            elif b.kind == L.CLICK_SYNC:
                pt.tool(p, self._nudged(b), b.kind, m.click_sync_lit, tone, hover)
                if m.click_sync_failed:
                    pt.warning_dot(p, self._nudged(b), tone)
            elif b.kind == L.KEYSET:
                pt.keyset(p, self._nudged(b), b.number, b.number == m.active,
                          tone, hover)
            elif b.kind == L.ADD:
                pt.add(p, self._nudged(b), m.hidden_sets, tone, hover)

    def _paint_flat_dimmed(self, p: QPainter) -> None:
        """Flat dims the group as a whole (42% opacity), so it is painted
        to a layer first: a ring over a fill must fade as one thing."""
        k = self._scale
        # Device pixels per widget pixel, whatever scales the painter.
        unit = paint._device_scale(p) / k
        layer = QPixmap(max(1, int(round(self.width() * unit))),
                        max(1, int(round(self.height() * unit))))
        layer.setDevicePixelRatio(unit)
        layer.fill(Qt.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.Antialiasing, True)
        lp.setRenderHint(QPainter.TextAntialiasing, True)
        lp.scale(k, k)
        lp.translate(MARGIN, MARGIN)
        self._paint_dimmable(lp, paint.identity)
        lp.end()
        p.save()
        p.translate(-MARGIN, -MARGIN)
        p.scale(1.0 / k, 1.0 / k)
        p.setOpacity(p.opacity() * tokens.FLAT_DIM_OPACITY)
        p.drawPixmap(QPointF(0.0, 0.0), layer)
        p.restore()

    # -- pointer ------------------------------------------------------------

    def _set_hover(self, key: tuple[str, int] | None) -> None:
        if key == self._hover:
            return
        self._hover = key
        clickable = key is not None and key[0] not in (L.PORTRAIT, L.NAME)
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.hover_changed.emit(*(key or ("", 0)))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        block = self._hit(event.position())
        self._set_hover(block.key if block else None)

    def leaveEvent(self, event) -> None:
        self._set_hover(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        block = self._hit(event.position())
        if block is None:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._pressed = block.key
            self.update()
        elif event.button() == Qt.RightButton:
            self.context_requested.emit(block.kind, block.number)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pressed, self._pressed = self._pressed, None
        self.update()
        block = self._hit(event.position())
        if pressed is not None and block is not None and block.key == pressed:
            self.clicked.emit(block.kind, block.number)

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            block = self._hit(event.pos())
            text = self.tooltip_for(block) if block else ""
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def tooltip_for(self, block: L.Block) -> str:
        m = self._model
        if block.kind == L.KEEP_ALIVE:
            return "Keep-Alive"
        if block.kind == L.CLICK_SYNC:
            if m.click_sync_state == "error":
                return f"Click Sync: {m.click_sync_error or 'not working'}"
            if m.click_sync_state == "armed":
                return "Click Sync: waiting for a second toon"
            return "Click Sync"
        if block.kind == L.KEYSET:
            return f"Keyset {block.number} · right-click for options"
        if block.kind == L.ADD:
            return ("Show a hidden keyset or add one" if m.hidden_sets
                    else "Add keyset")
        if block.kind == L.ENABLE:
            return "Disable toon" if m.enabled else "Enable toon"
        if block.kind == L.HOME:
            return "MultiTool"
        return ""
