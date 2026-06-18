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

from PySide6.QtCore import (
    Qt, QSize, QRectF, QPointF, Property, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QGraphicsColorizeEffect,
)

from tabs.multitoon._layout_utils import clear_layout
from utils.color_math import darken_rgb


# ── Geometry (exact values from the design handoff) ────────────────────────
CARD_RADIUS = 20
CARD_BORDER = 5
CARD_PAD = 18
CARD_MIN_H = 232
GRID_GAP = 18

PORTRAIT = 172
PORTRAIT_RING = 4
CUTOUT_R = 96
EMBLEM = 156

CTRL_W = 158
TOGGLE_W, TOGGLE_H = 34, 36
KA_PILL_H = 38
KEYSET_H = 38
KA_DOT = 28              # lightning toggle diameter inside the KA pill

STATUS_TOP_MARGIN = 14

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


def _card_body_path(w: float, h: float, cutout: str) -> QPainterPath:
    """The card body outline: a 20px rounded rect with one corner carved out by
    a 96px circle. Shared by the card background and the glow so both follow the
    exact same shape (including the concave cutout)."""
    rect = QRectF(0.5, 0.5, w - 1, h - 1)
    rounded = QPainterPath()
    rounded.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
    corners = {
        "tl": QPointF(0, 0), "tr": QPointF(w, 0),
        "bl": QPointF(0, h), "br": QPointF(w, h),
    }
    cut = QPainterPath()
    cut.addEllipse(corners[cutout], CUTOUT_R, CUTOUT_R)
    return rounded.subtracted(cut)


# Accent glow. We PAINT it (a gaussian blur of the card shape, blitted behind
# the cards) rather than use a QGraphicsDropShadowEffect: on macOS the effect's
# output is clipped to the cell's square bounds, leaving sharp square corners
# behind the rounded card. A painted pixmap has no such clipping, so the glow
# follows the rounded body + concave cutout exactly.
GLOW_BLUR = 22          # gaussian radius (smaller = tighter, less visible)
GLOW_ALPHA = 105        # peak accent alpha of the glow source (lower = fainter)
# Padding the grid keeps around the cards so the painted halo has room to fade.
GLOW_ROOM = 34


def _make_glow_pixmap(w: int, h: int, cutout: str, accent: QColor):
    """Return (pixmap, pad): the card shape filled with `accent` and gaussian-
    blurred on a transparent canvas padded by `pad`. Blit at (x - pad, y - pad)
    to lay a soft accent halo around the card that follows its exact shape."""
    from PySide6.QtWidgets import (
        QGraphicsScene, QGraphicsBlurEffect, QGraphicsPixmapItem,
    )
    pad = int(GLOW_BLUR * 2.5)
    pw, ph = int(w + 2 * pad), int(h + 2 * pad)
    src = QPixmap(pw, ph)
    src.fill(Qt.transparent)
    p = QPainter(src)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    path = _card_body_path(w, h, cutout)
    path.translate(pad, pad)
    col = QColor(accent)
    col.setAlpha(GLOW_ALPHA)
    p.fillPath(path, col)
    p.end()

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(src)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(GLOW_BLUR)
    item.setGraphicsEffect(blur)
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
        self._cache = {}   # (w,h,cutout,accent_rgba) -> (pixmap, pad)

    def set_cards(self, specs) -> None:
        cards = []
        for s in specs:
            w, h = int(s["w"]), int(s["h"])
            if w <= 0 or h <= 0:
                continue
            rw, rh = ((w + 7) // 8) * 8, ((h + 7) // 8) * 8   # round so drags reuse cache
            accent = QColor(s["accent"])
            key = (rw, rh, s["cutout"], accent.rgba())
            entry = self._cache.get(key)
            if entry is None:
                entry = _make_glow_pixmap(rw, rh, s["cutout"], accent)
                self._cache[key] = entry
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
    a 96px circle, filled with a deep accent gradient and bordered by a 5px
    inner accent stroke. The carved corner lets the central emblem nest in.

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
        self._dimmed = True

    def configure(self, accent: QColor, dimmed: bool) -> None:
        self._accent = QColor(accent)
        self._dimmed = bool(dimmed)
        self.update()

    def _body_path(self) -> QPainterPath:
        return _card_body_path(self.width(), self.height(), self._cutout)

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = self._body_path()

        # Body gradient: deep, rich version of the accent. darken() multiplies
        # each channel; the dim treatment scales brightness down further (the
        # saturation half of saturate(0.45) is handled by the colorize effect).
        bright = 0.75 if self._dimmed else 1.0
        top = darken_rgb(darken_rgb(self._accent, 0.28), bright)
        bot = darken_rgb(darken_rgb(self._accent, 0.14), bright)
        grad = QLinearGradient(0, 0, self.width() * 0.38, self.height())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.fillPath(path, grad)

        # 5px inner border: stroke the body path at double width and clip to
        # the path so only the inner half survives - a clean border that
        # follows the concave curve.
        border = darken_rgb(self._accent, 0.62) if self._dimmed else self._accent
        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, CARD_BORDER * 2))
        p.drawPath(path)
        p.restore()
        p.end()


# ── Portrait frame (4px accent ring + dark inner disc around the portrait) ──
class _PortraitFrame(QWidget):
    """172px circular frame: dark inner disc + 4px accent ring, hosting the
    shared ToonPortraitWidget inset inside the ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PORTRAIT, PORTRAIT)
        self.setStyleSheet("background: transparent;")
        self._ring = QColor("#555555")
        self._dimmed = True

    def configure(self, ring: QColor, dimmed: bool) -> None:
        self._ring = QColor(ring)
        self._dimmed = bool(dimmed)
        self.update()

    def host_geometry(self) -> tuple[int, int, int, int]:
        inset = PORTRAIT_RING
        return (inset, inset, PORTRAIT - 2 * inset, PORTRAIT - 2 * inset)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = cy = PORTRAIT / 2.0
        # Dark inner background (rgba(0,0,0,0.22)).
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 56))
        p.drawEllipse(QPointF(cx, cy), cx - 0.5, cy - 0.5)
        # 4px accent ring on the outer edge.
        ring = darken_rgb(self._ring, 0.62) if self._dimmed else self._ring
        pen = QPen(ring, PORTRAIT_RING)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = (PORTRAIT - PORTRAIT_RING) / 2.0
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ── Central emblem (app icon nested in the grid centre) ────────────────────
class _Emblem(QWidget):
    """156px circle: opaque bg-app fill + app icon, with a pulsing blue ring
    when broadcasting. Passive - reflects state only, never interactive."""

    _RING_MARGIN = 14  # room for the -4px ring + soft glow outside the disc

    def __init__(self, parent=None):
        super().__init__(parent)
        side = EMBLEM + 2 * self._RING_MARGIN
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
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

    def stop(self) -> None:
        self._anim.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        cx = cy = self.width() / 2.0
        r = EMBLEM / 2.0

        # Pulsing ring + soft glow just outside the disc (broadcasting only).
        if self._broadcasting:
            glow = QColor(self._ring)
            glow.setAlphaF(0.55 * self._pulse)
            p.setPen(QPen(glow, 8))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)
            ring = QColor(self._ring)
            ring.setAlphaF(self._pulse)
            p.setPen(QPen(ring, 2))
            p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)

        # Opaque bg-app disc so the carved card cutouts read as a clean ring.
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_app)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # App icon, inset 8px, clipped circular.
        pm = self._icon if self._broadcasting else self._icon_grey
        if not pm.isNull():
            inset = 8
            d = EMBLEM - 2 * inset
            clip = QPainterPath()
            clip.addEllipse(QPointF(cx, cy), d / 2.0, d / 2.0)
            p.setClipPath(clip)
            target = QRectF(cx - d / 2.0, cy - d / 2.0, d, d)
            scaled = pm.scaled(int(d), int(d), Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
            p.drawPixmap(target, scaled, QRectF(scaled.rect()))
        p.end()


def img_fmt():
    from PySide6.QtGui import QImage
    return QImage.Format_ARGB32


# ── The layout ─────────────────────────────────────────────────────────────
class _CompactLayout(QWidget):
    """Pinwheel Multitoon layout. Public surface consumed by MultitoonTab:
    `populate`, `set_card_brand`, `apply_theme`, `_set_keep_alive_collapsed`,
    `_animate_keep_alive_visibility`, `deactivate`, `_position_cards`."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cells: list[dict] = []
        self._emblem: _Emblem | None = None
        self._glow: _GlowLayer | None = None
        self._grid_host: QWidget | None = None
        self._build_structure()
        self.populate()

    # ── Structure ──────────────────────────────────────────────────────────
    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(0)

        # Grid host holds the painted glow layer, the 2x2 cards, and the centre
        # emblem. The grid's inner margin gives each painted halo room to fade.
        self._grid_host = QWidget()
        grid = QGridLayout(self._grid_host)
        grid.setContentsMargins(GLOW_ROOM, GLOW_ROOM, GLOW_ROOM, GLOW_ROOM)
        grid.setSpacing(GRID_GAP)
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

        # cell: holds the dim colorize effect (attached only when dimmed).
        cell = QFrame()
        cell.setObjectName(f"pin_cell_{i}")
        cell.setStyleSheet(f"#pin_cell_{i} {{ background: transparent; border: none; }}")
        cell.setMinimumSize(0, CARD_MIN_H)
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
        content.setContentsMargins(CARD_PAD, CARD_PAD, CARD_PAD, CARD_PAD)
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
        ctrl_wrap.setFixedWidth(CTRL_W)
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
            "portrait_frame": portrait_frame,
            "toggle_row": toggle_row,
            "ka_pill": ka_pill,
            "ka_lay": ka_lay,
            "sel_holder": sel_holder,
            "name_holder": name_holder,
            "stats_row": stats_row,
            "cfg": cfg,
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

        self._relayout_all()
        self._apply_initial_brands()

    def _populate_cell(self, i: int, cell: dict):
        tab = self._tab
        cfg = cell["cfg"]
        align = Qt.AlignRight if not cfg["left"] else Qt.AlignLeft

        # Portrait: host the shared 172px badge inside the ring frame.
        badge = tab.slot_badges[i]
        badge.setMinimumSize(0, 0)
        hx, hy, hw, hh = cell["portrait_frame"].host_geometry()
        badge.setParent(cell["portrait_frame"])
        badge.setFixedSize(hw, hh)
        badge.move(hx, hy)
        badge.set_border_color(None)
        badge.show()

        # Status dot overlays the portrait's outer-bottom corner.
        _, status_dot = tab.toon_labels[i]
        status_dot.set_size(34)
        status_dot.setParent(cell["portrait_frame"])

        # Toggle row: enable / chat / click-sync.
        for b in (tab.toon_buttons[i], tab.chat_buttons[i], tab.click_sync_buttons[i]):
            b.setText("")
            b.setFixedSize(TOGGLE_W, TOGGLE_H)
            b.setIconSize(QSize(17, 17))
        clear_layout(cell["toggle_row"])
        cell["toggle_row"].addWidget(tab.toon_buttons[i])
        cell["toggle_row"].addWidget(tab.chat_buttons[i])
        cell["toggle_row"].addWidget(tab.click_sync_buttons[i])
        cell["toggle_row"].addStretch(1)

        # Keep-alive pill leaf: lightning toggle + progress bar.
        ka_btn = tab.keep_alive_buttons[i]
        ka_btn.setFixedSize(KA_DOT, KA_DOT)
        ka_btn.setIconSize(QSize(13, 13))
        ka_bar = tab.ka_progress_bars[i]
        ka_bar.setFixedHeight(9)
        ka_bar.setMinimumWidth(40)
        ka_bar.setMaximumWidth(16777215)
        clear_layout(cell["ka_lay"])
        cell["ka_lay"].addWidget(ka_btn)
        cell["ka_lay"].addWidget(ka_bar, 1)

        # Keyset stepper leaf (shared SetSelectorWidget).
        sel = tab.set_selectors[i]
        sel.setFixedHeight(KEYSET_H)
        sel.setMinimumWidth(0)
        sel.setMaximumWidth(16777215)
        if hasattr(sel, "set_paint_scale"):
            sel.set_paint_scale(1.0)
        clear_layout(cell["sel_holder"])
        cell["sel_holder"].addWidget(sel)

        # Name leaf: name expands to the card's outer edge so it elides.
        name_label, _ = tab.toon_labels[i]
        name_font = QFont()
        name_font.setPixelSize(23)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setAlignment(align | Qt.AlignVCenter)
        clear_layout(cell["name_holder"])
        cell["name_holder"].addWidget(name_label, 1)

        # Stats leaf: laff + beans, aligned to the outer edge.
        for lbl in (tab.laff_labels[i], tab.bean_labels[i]):
            lbl.setFixedHeight(22)
            lbl.setIconSize(QSize(16, 16))
            stat_font = QFont()
            stat_font.setPixelSize(15)
            stat_font.setWeight(QFont.DemiBold)
            lbl.setFont(stat_font)
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
        cell = self._cells[i]
        tab = self._tab

        wids = tab.window_manager.ttr_window_ids if hasattr(tab, "window_manager") else []
        window_available = i < len(wids)
        is_toon = game in ("cc", "ttr")

        # Accent: per-toon override, else the game brand colour.
        if game == "cc":
            accent = resolve_accent(self._entry(i, "cc"), QColor(c["game_pill_cc"]))
        elif game == "ttr":
            accent = resolve_accent(self._entry(i, "ttr"), QColor(c["game_pill_ttr"]))
        else:
            accent = QColor(c["border_light"])

        active = bool(enabled) and window_available and is_toon
        cell["dimmed"] = not active
        cell["accent"] = QColor(accent)
        cell["active"] = active

        cell["bg"].configure(accent, dimmed=not active)
        cell["portrait_frame"].configure(accent, dimmed=not active)
        self._apply_cell_effects(cell, accent, active)
        self._refresh_glow()

        # Layout-owned control chrome: the KA pill container + the keyset
        # stepper colour. The five toggle buttons themselves are styled by
        # MultitoonTab (single style-writer per control); the cell's dim
        # effect desaturates them in place when the card is off/stopped.
        self._style_ka_pill(i)
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
        """Dimmed cards get a desaturating colorize on the cell; lit cards have
        no cell effect. The accent glow is painted by the _GlowLayer (not a
        QGraphicsDropShadowEffect, which clips to a square on macOS)."""
        cell_w = cell["cell"]
        if active:
            if cell_w.graphicsEffect() is not None:
                cell_w.setGraphicsEffect(None)
        else:
            eff = cell_w.graphicsEffect()
            if not isinstance(eff, QGraphicsColorizeEffect):
                eff = QGraphicsColorizeEffect(cell_w)
                eff.setColor(QColor("#808080"))
                cell_w.setGraphicsEffect(eff)
            eff.setStrength(0.55)

    # ── Control chrome owned by the layout ───────────────────────────────────
    def _style_ka_pill(self, i: int) -> None:
        """The keep-alive pill is a layout-owned container (the lightning
        toggle inside it + the progress bar are styled by MultitoonTab)."""
        cell = self._cells[i]
        ka_pill = cell.get("ka_pill")
        if ka_pill is not None:
            ka_pill.setStyleSheet(
                f"QFrame#ka_pill_{i} {{ background: rgba(0,0,0,0.24);"
                f" border: 1px solid rgba(0,0,0,0.30); border-radius: 19px; }}"
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
    def _set_keep_alive_collapsed(self, collapsed: bool) -> None:
        for cell in self._cells:
            pill = cell.get("ka_pill")
            if pill is not None:
                pill.setVisible(not collapsed)

    def _animate_keep_alive_visibility(self, target_visible: bool) -> None:
        # Snap visibility (the design's fade is cosmetic; snapping avoids the
        # offscreen QGraphicsOpacityEffect crash path).
        self._set_keep_alive_collapsed(not target_visible)

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
        # Find this cell's status dot among the shared toon_labels.
        idx = self._cells.index(cell)
        if idx < len(self._tab.toon_labels):
            dot = self._tab.toon_labels[idx][1]
        if dot is None or dot.parentWidget() is not frame:
            return
        # Bottom-right inner corner of the 172px circle.
        d = dot.width()
        off = int(PORTRAIT * 0.5 + (PORTRAIT * 0.5) * 0.70) - d // 2
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

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout_all()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_all()
