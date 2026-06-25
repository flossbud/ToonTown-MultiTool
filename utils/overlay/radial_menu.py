"""Interactive radial menu widget for the emblem overlay.

Paints a ring of azure circles around the emblem center and routes clicks to
intent signals. The soft radial dim behind the ring is a separate click-through
layer (RadialDimWidget) so it can sit behind the emblem while the buttons stay
in front of it. The main ring has two variants
(selected by the ``variant`` ctor arg): transparent mode (Accounts, Window,
Settings, Back, Exit) and windowed mode (Accounts, Float, Back). Clicking
Accounts opens the accounts sub-ring (Back plus up to 8 recent accounts rendered
as their toon's customized portrait, with a green dot for a running account). Supports a staggered left-to-right pop-in reveal, hover labels,
Esc-to-close, and a 15s idle auto-hide. Geometry comes from
utils/radial_menu_layout.py; account portraits from utils/overlay/radial_portrait.py.
"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import (Qt, QRectF, QPointF, Signal, QTimer, QElapsedTimer,
                            Property, QEasingCurve, QVariantAnimation)
from PySide6.QtGui import (QPainter, QColor, QBrush, QPen, QLinearGradient,
                           QRadialGradient, QPainterPath, QFont, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils.radial_menu_layout import (MAIN_RING_ANGLES, WINDOWED_RING_ANGLES,
                                       account_ring_angles, polar_point)
from utils.image_blur import gaussian_blur_pixmap

_OUT_CUBIC = QEasingCurve.OutCubic
_IN_CUBIC = QEasingCurve.InCubic

_MAIN_KEYS_BY_VARIANT = {
    "transparent": ("accounts", "home", "settings", "close", "exit"),
    "windowed":    ("accounts", "transparent", "close"),
}
_MAIN_BOTTOM_KEYS = ("close", "exit")   # labels render below these
# Hover labels. "close" dismisses the ring (one level up), so it reads as "Back"
# (the X glyph next to "Exit" was confusingly two ways to leave).
_MAIN_LABELS = {"accounts": "Accounts", "home": "Window", "settings": "Settings",
                "transparent": "Float", "close": "Back", "exit": "Exit"}
# NOTE: the "home" key (Window spoke) returns to the windowed app; the internal
# key/signal names stay "home" while the user-facing label is "Window".


# --- easing + interpolation (pure, unit-testable) -----------------------------

def _clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_out(t: float) -> float:
    """Decelerating cubic: fast start, soft landing (entrance fly-out)."""
    t = _clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def _ease_in(t: float) -> float:
    """Accelerating cubic: soft start, fast finish (exit fly-back)."""
    t = _clamp01(t)
    return t ** 3


def _ease_spring(t: float) -> float:
    """Overshoot-and-settle (easeOutBack) for the press spring-back."""
    t = _clamp01(t)
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


def _dim_frame(progress: float) -> tuple:
    """(opacity, scale) for the frosted dim backdrop at animation progress in
    [0,1]. Opacity drives the fade + focus-pull (a blurred copy fades in over the
    live sharp content); scale drives the iris-expand from the emblem center."""
    eased = _ease_out(_clamp01(progress))
    return eased, _lerp(0.12, 1.0, eased)


def radial_anim_enabled() -> bool:
    """True when ring animations should run: the TTMT_NO_RADIAL_ANIM kill switch
    is off AND reduce-motion is off. Mirrors RadialMenuWidget's env gate and
    additionally honors the project's reduce-motion preference for the backdrop."""
    if os.environ.get("TTMT_NO_RADIAL_ANIM") in ("1", "true", "yes", "on"):
        return False
    try:
        from utils.motion import is_reduced
        return not is_reduced()
    except Exception:
        return True


# --- glyph + disc painters (azure theme matching the emblem) ------------------

def _disc(p: QPainter, cx: float, cy: float, r: float, hot: bool = False,
          danger: bool = False) -> None:
    """Refined glossy disc face (azure, or red for danger): dark backing ring, a
    3-stop vertical gradient, a clipped top sheen, and a bright rim. The focus
    glow halo is NO LONGER drawn here - it is hover-only via _focus_glow()."""
    if danger:
        top, mid, bot = QColor(255, 120, 108), QColor(232, 64, 58), QColor(196, 28, 28)
        rim = QColor(255, 180, 170, 210)
    else:
        top, mid, bot = QColor(95, 212, 255), QColor(0, 168, 250), QColor(0, 108, 224)
        rim = QColor(160, 228, 255, 210)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(8, 10, 14))
    p.drawEllipse(QPointF(cx, cy), r + 3, r + 3)        # dark backing
    g = QLinearGradient(cx, cy - r, cx, cy + r)
    g.setColorAt(0.0, top); g.setColorAt(0.5, mid); g.setColorAt(1.0, bot)
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.save()
    clip = QPainterPath(); clip.addEllipse(QPointF(cx, cy), r, r)
    p.setClipPath(clip)
    sheen = QLinearGradient(cx, cy - r, cx, cy + r * 0.15)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 130 if hot else 108))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(sheen)); p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(cx, cy - r * 0.42), r * 0.80, r * 0.52)
    p.restore()
    pen = QPen(rim); pen.setWidthF(max(1.0, r * 0.035))
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r - 0.8, r - 0.8)


def _drop_shadow(p: QPainter, cx: float, cy: float, r: float, depth: float = 1.0) -> None:
    """Soft 'floating' cast shadow under a disc. `depth` (>=1.0) deepens the
    offset + spread + opacity so hover can sink the shadow further."""
    dy = r * 0.18 * depth
    blur = r * 0.50 * (0.85 + 0.30 * depth)
    alpha = int(130 * min(1.0, depth))
    sg = QRadialGradient(QPointF(cx, cy + dy), r + blur)
    sg.setColorAt(0.0, QColor(0, 0, 0, alpha))
    sg.setColorAt(0.6, QColor(0, 0, 0, int(alpha * 0.55)))
    sg.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(sg))
    p.drawEllipse(QPointF(cx, cy + dy), r + blur, r + blur)


def _focus_glow(p: QPainter, cx: float, cy: float, r: float, strength: float,
                danger: bool = False) -> None:
    """Azure (or red) halo behind a disc, drawn ONLY on hover. strength in [0,1]."""
    if strength <= 0.0:
        return
    a = int(180 * _clamp01(strength))
    if danger:
        c0, c1, c2 = (255, 70, 60), (225, 45, 40), (190, 25, 25)
    else:
        c0, c1, c2 = (0, 185, 249), (0, 150, 245), (0, 120, 239)
    glow = QRadialGradient(QPointF(cx, cy), r * 1.9)
    glow.setColorAt(0.0, QColor(c0[0], c0[1], c0[2], a))
    glow.setColorAt(0.5, QColor(c1[0], c1[1], c1[2], int(a * 0.45)))
    glow.setColorAt(1.0, QColor(c2[0], c2[1], c2[2], 0))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(cx, cy), r * 1.9, r * 1.9)


def _gear(p: QPainter, cx: float, cy: float, s: float) -> None:
    # Matches utils/icon_factory.py:make_nav_gear (8 trapezoid teeth + center hole).
    n = 8; r_o = s * 0.44; r_i = s * 0.30; r_h = s * 0.13; ht = math.pi / n * 0.6
    gear = QPainterPath()
    for i in range(n):
        b = math.radians(i * 360 / n)
        pt = lambda r, a: (cx + r * math.cos(a), cy + r * math.sin(a))
        (gear.moveTo if i == 0 else gear.lineTo)(*pt(r_i, b - ht))
        gear.lineTo(*pt(r_o, b - ht * 0.4)); gear.lineTo(*pt(r_o, b + ht * 0.4)); gear.lineTo(*pt(r_i, b + ht))
    gear.closeSubpath()
    hole = QPainterPath(); hole.addEllipse(QRectF(cx - r_h, cy - r_h, r_h * 2, r_h * 2))
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255))
    p.drawPath(gear.subtracted(hole))


def _person(p: QPainter, cx: float, cy: float, r: float) -> None:
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255))
    hr = r * 0.42
    p.drawEllipse(QPointF(cx, cy - r * 0.38), hr, hr)
    body = QPainterPath(); bw = r * 1.25; bh = r * 1.05
    body.addRoundedRect(QRectF(cx - bw / 2, cy + r * 0.02, bw, bh), bw * 0.5, bw * 0.5)
    p.drawPath(body)


def _window_frame(p: QPainter, cx: float, cy: float, r: float) -> None:
    """White app window with a dark title-bar seam. Used for the "Window" spoke
    that returns to the app; pairs stylistically with the Float cards glyph."""
    p.setPen(Qt.NoPen)
    w, h, rad = r * 1.52, r * 1.20, r * 0.16
    x0, y0 = cx - w / 2, cy - h / 2
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(x0, y0, w, h), rad, rad)
    tb = h * 0.34
    p.setBrush(QColor(10, 12, 16))           # title-bar seam -> reads as a window
    p.drawRect(QRectF(x0, y0 + tb, w, max(1.6, r * 0.12)))


def _x_glyph(p: QPainter, cx: float, cy: float, r: float) -> None:
    """White X. Used on the red Exit (quit-the-app) spoke."""
    s = r * 0.46
    pen = QPen(QColor(255, 255, 255)); pen.setWidthF(max(2.0, r * 0.22))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
    p.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))


def _back_arrow(p: QPainter, cx: float, cy: float, r: float) -> None:
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255))
    s = r * 0.62
    p.drawPolygon(QPolygonF([QPointF(cx - s, cy),
                             QPointF(cx - s * 0.05, cy - s * 0.62),
                             QPointF(cx - s * 0.05, cy + s * 0.62)]))
    p.drawRect(QRectF(cx - s * 0.05, cy - s * 0.20, s * 1.05, s * 0.40))


def _overlay_cards(p: QPainter, cx: float, cy: float, r: float) -> None:
    """Go-Transparent glyph: two overlapping tall 'floating cards' (front offset
    up-and-right with a dark seam), white on the azure disc - the literal picture
    of TTMT's overlay cards floating on top, and the inverse of the home glyph."""
    p.setPen(Qt.NoPen)
    cw, ch, rad = r * 0.82, r * 1.04, r * 0.16
    bxc, byc = cx - r * 0.28, cy + r * 0.26          # back card, down-left
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(bxc - cw / 2, byc - ch / 2, cw, ch), rad, rad)
    fxc, fyc = cx + r * 0.26, cy - r * 0.24          # front card, up-right
    gap = r * 0.12
    p.setBrush(QColor(10, 12, 16))                   # dark seam separates the cards
    p.drawRoundedRect(QRectF(fxc - cw / 2 - gap, fyc - ch / 2 - gap,
                             cw + 2 * gap, ch + 2 * gap), rad + gap, rad + gap)
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(fxc - cw / 2, fyc - ch / 2, cw, ch), rad, rad)


def _status_dot(p: QPainter, cx: float, cy: float, r: float) -> None:
    """Green 'running' indicator at the lower-right of an account portrait."""
    dr = r * 0.30
    dx = cx + r * 0.64
    dy = cy + r * 0.64
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(10, 12, 16))
    p.drawEllipse(QPointF(dx, dy), dr + 2.5, dr + 2.5)   # dark rim for contrast
    p.setBrush(QColor(64, 220, 96))
    p.drawEllipse(QPointF(dx, dy), dr, dr)


def _account_frame(p: QPainter, cx: float, cy: float, r: float, hot: bool) -> None:
    """Dark rim ring behind an account portrait. The Floating shadow and the
    hover focus glow are drawn by _paint_accounts (so this matches the spokes)."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(10, 12, 16))
    p.drawEllipse(QPointF(cx, cy), r + 2, r + 2)


_SPIN_PERIOD_MS = 900   # one full spinner rotation


def _loading_spinner(p: QPainter, cx: float, cy: float, r: float, phase: float) -> None:
    """A subtle rotating arc drawn over a pending (background-only) portrait.
    `phase` is in [0,1) and advances continuously while the pose is pending."""
    p.save()
    sr = r * 0.5
    pen = QPen(QColor(255, 255, 255, 150))
    pen.setWidthF(max(1.5, r * 0.12))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    rect = QRectF(cx - sr, cy - sr, sr * 2.0, sr * 2.0)
    # Qt arc angles are in 1/16 degree; negative span direction rotates CW.
    start = int((-phase * 360.0) * 16)
    p.drawArc(rect, start, 280 * 16)
    p.restore()


def _label_at(p: QPainter, cx: float, cy: float, text: str) -> None:
    f = QFont("DejaVu Sans"); f.setPixelSize(18); f.setBold(True); p.setFont(f)
    fm = p.fontMetrics(); tw = fm.horizontalAdvance(text)
    pad = 10; pw = tw + pad * 2; ph = fm.height() + 8
    px = cx - pw / 2; py = cy - ph / 2
    rect = QRectF(px, py, pw, ph)
    p.setBrush(QColor(12, 16, 24, 238))
    border = QPen(QColor(120, 190, 255, 70)); border.setWidthF(1.0)
    p.setPen(border)
    p.drawRoundedRect(rect, ph / 2, ph / 2)
    p.setPen(QColor(235, 242, 250))
    p.drawText(rect, Qt.AlignCenter, text)


def _label_pill(p: QPainter, cx: float, cy: float, r: float, text: str, above: bool) -> None:
    f = QFont("DejaVu Sans"); f.setPixelSize(18); f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics(); tw = fm.horizontalAdvance(text)
    pad = 10; pw = tw + pad * 2; ph = fm.height() + 8
    px = cx - pw / 2
    py = (cy - r - 8 - ph) if above else (cy + r + 8)
    rect = QRectF(px, py, pw, ph)
    p.setBrush(QColor(12, 16, 24, 235))
    border = QPen(QColor(120, 190, 255, 70)); border.setWidthF(1.0)
    p.setPen(border)
    p.drawRoundedRect(rect, ph / 2, ph / 2)
    p.setPen(QColor(235, 242, 250))
    p.drawText(rect, Qt.AlignCenter, text)


class RadialDimWidget(QWidget):
    """The radial menu's frosted-blur backdrop, as its OWN click-through layer.

    Sits behind the emblem (z-order: cards -> dim -> emblem -> buttons) and is
    purely decorative (never grabs input). Renders a frozen, blurred snapshot of
    whatever was behind the ring at open time, plus a soft dark veil, masked to a
    soft circular falloff. Animates in/out with a combined iris-expand +
    focus-pull driven by the ``progress`` property: the widget is transparent, so
    at progress 0 the live sharp content shows straight through, and we fade the
    blurred copy in on top (the focus-pull falls out of the layering for free).

    No QGraphicsEffect: all compositing stays inside one QPainter (see
    utils/widgets/backdrop_blur.py for the rationale - QGraphicsEffect renders
    invisibly on proxied widgets and risks the Py3.14/PySide6 paint-time GC SEGV).
    """

    _OPEN_MS = 240
    _CLOSE_MS = 200
    _BLUR_RADIUS = 10
    _VEIL = QColor(8, 10, 16, 105)   # ~0.41 center veil (lighter than the old 150)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._raw = None            # source region pixmap (kept for lazy rebuild)
        self._frost = None          # cached composite (blurred backdrop + veil + mask)
        self._progress = 0.0
        self._anim = None           # QVariantAnimation while reveal/close runs

    # --- backdrop -----------------------------------------------------------
    def set_backdrop(self, raw) -> None:
        """Bake the cached frost composite from a raw region pixmap, or a
        veil-only composite when ``raw`` is None/empty (graceful fallback). The
        source is retained so paintEvent can rebuild lazily if the widget is still
        0-size / pre-layout now (the overlay surface may not have propagated
        geometry yet); the build is skipped here and retried on first paint."""
        self._raw = raw
        self._frost = self._build_frost(raw)
        self.update()

    def _build_frost(self, raw):
        from PySide6.QtGui import QPixmap
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return None
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        cx = size.width() / 2.0
        cy = size.height() / 2.0
        radius = min(size.width(), size.height()) / 2.0
        if radius <= 0:
            return pm
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 1) blurred backdrop snapshot (skipped on the veil-only fallback)
        if raw is not None and not raw.isNull():
            blurred = gaussian_blur_pixmap(raw, self._BLUR_RADIUS)
            scaled = blurred.scaled(size, Qt.IgnoreAspectRatio,
                                    Qt.SmoothTransformation)
            p.drawPixmap(0, 0, scaled)
        # 2) soft dark veil
        c = self._VEIL
        clear = QColor(c.red(), c.green(), c.blue(), 0)
        veil = QRadialGradient(QPointF(cx, cy), radius)
        veil.setColorAt(0.0, c)
        veil.setColorAt(0.52, c)
        veil.setColorAt(0.86, clear)
        veil.setColorAt(1.0, clear)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(veil))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        # 3) radial soft-edge mask: carve the whole composite into a soft disc
        mask = QRadialGradient(QPointF(cx, cy), radius)
        mask.setColorAt(0.0, QColor(0, 0, 0, 255))
        mask.setColorAt(0.60, QColor(0, 0, 0, 255))
        mask.setColorAt(0.78, QColor(0, 0, 0, 0))
        mask.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.setBrush(QBrush(mask))
        p.drawRect(0, 0, size.width(), size.height())
        p.end()
        return pm

    # --- progress property + paint -----------------------------------------
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def paintEvent(self, e):
        # Lazy (re)build: set_backdrop may have run while the widget was still
        # 0-size / pre-layout (the overlay surface doesn't propagate geometry
        # synchronously), leaving _frost None. By first paint the widget has its
        # real size, so rebuild then; also rebuild if the size changed under us.
        if self._frost is None or self._frost.size() != self.size():
            self._frost = self._build_frost(self._raw)
        if self._frost is None or self._frost.isNull():
            return
        opacity, scale = _dim_frame(self._progress)
        if opacity <= 0.0:
            return
        w = float(self.width())
        h = float(self.height())
        sw = w * scale
        sh = h * scale
        target = QRectF((w - sw) / 2.0, (h - sh) / 2.0, sw, sh)
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(opacity)
        p.drawPixmap(target, self._frost, QRectF(self._frost.rect()))
        p.end()

    # --- animation ----------------------------------------------------------
    def start_reveal(self, animate: bool = True) -> None:
        """Animate the frost in (iris + focus-pull). ``animate=False`` snaps."""
        self._stop_anim()
        if not animate:
            self._set_progress(1.0)
            return
        self._run_anim(self._progress, 1.0, self._OPEN_MS, _OUT_CUBIC)

    def start_close(self, animate: bool = True) -> None:
        """Animate the frost out (collapse). ``animate=False`` snaps to hidden.
        Does not destroy the surface; the host's close path tears it down."""
        self._stop_anim()
        if not animate:
            self._set_progress(0.0)
            return
        self._run_anim(self._progress, 0.0, self._CLOSE_MS, _IN_CUBIC)

    def _run_anim(self, start, end, ms, curve) -> None:
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(ms)
        anim.setEasingCurve(curve)
        anim.valueChanged.connect(lambda v: self._set_progress(float(v)))
        anim.finished.connect(self._stop_anim)
        self._anim = anim
        anim.start()

    def _stop_anim(self) -> None:
        a = self._anim
        self._anim = None
        if a is not None:
            try:
                a.stop()
                a.deleteLater()   # don't accumulate self-owned anims across opens
            except Exception:
                pass


class RadialMenuWidget(QWidget):
    accounts_requested = Signal()
    home_requested = Signal()
    settings_requested = Signal()
    transparent_requested = Signal()
    close_requested = Signal()
    exit_requested = Signal()
    back_requested = Signal()
    account_clicked = Signal(str)
    closing = Signal()           # fly-back begun (all dismiss paths) -> dim collapse

    _IDLE_MS = 15000
    _APPEAR_MS = 360
    _APPEAR_STAGGER_MS = 70
    _CLOSE_MS = 240
    _CLOSE_STAGGER_MS = 45

    def __init__(self, emblem_diameter: float, customizations=None,
                 variant="transparent", parent=None):
        super().__init__(parent)
        self._emblem_dia = float(emblem_diameter)
        self._variant = variant
        self._main_keys = _MAIN_KEYS_BY_VARIANT[variant]
        self._main_angles = (MAIN_RING_ANGLES if variant == "transparent"
                             else WINDOWED_RING_ANGLES)
        self._sat_r = self._emblem_dia * 0.40 / 2.0   # satellite = 40% of emblem diameter
        self._ring = self._emblem_dia / 2.0 + 16.0 + self._sat_r   # 16px gap outside the emblem
        self._customizations = customizations
        self._state = "main"
        self._hover = None          # (state, key) or None
        self._accounts = []         # RingAccount entries for the accounts sub-ring
        self._portraits = {}        # account_id -> circular QPixmap (set in set_accounts)
        self._launched = set()      # indices clicked-to-launch in the current sub-ring
        self._loading = set()       # account_ids whose pose is pending (spinner)
        self._spinner_phase = 0.0   # [0,1) rotation of the loading spinner
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        # Calm the whole ring under Reduce Motion (and the kill switch): the
        # spoke fly-out honors both, matching the frosted dim backdrop.
        self._anim_enabled = radial_anim_enabled()
        self._appear_active = False
        self._appear_progress = {}     # key -> eased visibility in [0,1]
        self._stagger = {}             # key -> ms delay (entrance or exit)
        self._closing = False
        self._close_emitted = False
        self._close_progress = {}      # key -> eased close progress in [0,1]
        self._close_from = {}          # key -> vis at close-start (fly-back origin)
        self._hover_progress = {}      # key -> eased hover amount in [0,1]  (Task 5)
        self._press_hit = None         # (state, key) currently pressed       (Task 6)
        self._press_releasing = False
        self._press_t = 0.0            # depress amount while held
        self._press_rt = 0.0           # spring-back progress on release
        self._press_scale_val = 1.0
        self._elapsed = QElapsedTimer()
        self._clock = QTimer(self)
        self._clock.setInterval(16)    # ~60fps
        self._clock.timeout.connect(self._on_clock)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self._IDLE_MS)
        self._idle_timer.timeout.connect(self._begin_close)
        from utils.rendition_poses import RenditionPoseFetcher
        # Live-refresh: fill in a pending portrait when its pose lands. Qt
        # auto-disconnects this bound-method slot when the widget is destroyed.
        RenditionPoseFetcher.instance().pose_ready.connect(self._on_pose_ready)

    @property
    def state(self) -> str:
        return self._state

    def idle_timeout_ms(self) -> int:
        return self._IDLE_MS

    def reveal_order(self, state: str) -> list:
        """Keys for ``state`` ordered left-to-right by circle center-x."""
        if state == "main":
            keys = list(self._main_keys)
        else:
            keys = ["back"] + list(range(len(self._accounts)))
        return sorted(keys, key=lambda k: self.circle_geometry(state, k)[0])

    def start_reveal(self) -> None:
        """Begin the staggered Fly-Out entrance for the current state."""
        keys = self.reveal_order(self._state)
        order = {k: i for i, k in enumerate(keys)}      # left-to-right
        self._stagger = {k: order[k] * self._APPEAR_STAGGER_MS for k in keys}
        self._closing = False
        self._close_emitted = False
        self._close_progress = {}
        self._press_hit = None
        self._press_releasing = False
        self._press_t = 0.0
        self._press_rt = 0.0
        self._press_scale_val = 1.0
        self._hover_progress = {k: 0.0 for k in keys}
        self._arm_idle()
        if not self._anim_enabled:
            self._appear_active = False
            self._appear_progress = {k: 1.0 for k in keys}
            self.update()
            return
        self._appear_active = True
        self._appear_progress = {k: 0.0 for k in keys}
        self._elapsed.restart()
        self._kick()
        self.update()

    def _kick(self) -> None:
        """Ensure the animation clock is running (no-op if disabled/already on)."""
        if self._anim_enabled and not self._clock.isActive():
            self._clock.start()

    def _on_clock(self) -> None:
        self._advance(self._elapsed.elapsed())

    def _begin_close(self) -> None:
        """Play the reverse Fly-Back, then emit close_requested on completion.
        All dismiss paths (Esc, idle, the close spoke, all-accounts-launched)
        route through here so both hosts animate identically. Idempotent."""
        if self._closing:
            return
        self._idle_timer.stop()
        self.closing.emit()
        if not self._anim_enabled:
            # Synchronous close, but still latch the close flags so the guards
            # above and in activate_at hold (keeps _begin_close idempotent in
            # kill-switch mode, matching animated mode).
            self._closing = True
            self._close_emitted = True
            self.close_requested.emit()
            return
        keys = self.reveal_order(self._state)
        # Capture where each circle sits RIGHT NOW (mid-entrance or settled) so
        # the fly-back starts from the current position instead of snapping to
        # the full slot first. Read before flipping the state flags below.
        self._close_from = {k: self._circle_vis(k) for k in keys}
        self._appear_active = False
        self._closing = True
        self._close_emitted = False
        order = {k: i for i, k in enumerate(reversed(keys))}   # rightmost leaves first
        self._stagger = {k: order[k] * self._CLOSE_STAGGER_MS for k in keys}
        self._close_progress = {k: 0.0 for k in keys}
        self._elapsed.restart()
        self._kick()
        self.update()

    def _advance(self, now_ms: int) -> None:
        """Advance all active animations to the given elapsed time and repaint.
        The unit-test seam: tests call this directly with synthetic timestamps."""
        busy = False
        if self._appear_active:
            done = True
            for k, delay in self._stagger.items():
                raw = (now_ms - delay) / float(self._APPEAR_MS)
                self._appear_progress[k] = _ease_out(raw)
                if raw < 1.0:
                    done = False
            if done:
                self._appear_active = False
            else:
                busy = True
        if self._closing:
            done = True
            for k, delay in self._stagger.items():
                raw = (now_ms - delay) / float(self._CLOSE_MS)
                self._close_progress[k] = _ease_in(raw)
                if raw < 1.0:
                    done = False
            if done:
                if not self._close_emitted:
                    self._close_emitted = True
                    self.close_requested.emit()
            else:
                busy = True
        if self._advance_hover():
            busy = True
        if self._advance_press():
            busy = True
        # Scope to the accounts ring: _loading is only cleared by _on_pose_ready
        # while that sub-ring is showing, so gating here too keeps a leftover
        # pending id (e.g. user clicked Back before a pose arrived) from pinning
        # the clock at 60fps off-ring. Re-entering Accounts repopulates _loading.
        if self._state == "accounts" and self._loading:
            self._spinner_phase = (now_ms % _SPIN_PERIOD_MS) / float(_SPIN_PERIOD_MS)
            busy = True
        self.update()
        if not busy:
            self._clock.stop()

    def _advance_hover(self) -> bool:
        """Ease each key's hover amount toward 1 (hovered) or 0 (not). Returns
        True while any value is still in motion (keeps the clock alive)."""
        hovered = (self._hover[1]
                   if (self._hover and self._hover[0] == self._state) else None)
        busy = False
        for k in self.reveal_order(self._state):
            cur = self._hover_progress.get(k, 0.0)
            tgt = 1.0 if k == hovered else 0.0
            nxt = cur + (tgt - cur) * 0.30
            if abs(nxt - tgt) < 0.01:
                nxt = tgt
            elif abs(nxt - cur) > 1e-4:
                busy = True
            self._hover_progress[k] = nxt
        return busy

    def _advance_press(self) -> bool:
        """Depress the held spoke toward 0.88, then spring it back to 1.0 with
        overshoot on release. Increment-based (no timestamp). Returns True while
        in motion / still held."""
        if self._press_hit is None:
            return False
        if not self._press_releasing:
            self._press_t = min(1.0, self._press_t + 0.35)
            self._press_scale_val = 1.0 - 0.12 * self._press_t
            return True                       # keep ticking while held
        self._press_rt = min(1.0, self._press_rt + 0.08)
        self._press_scale_val = _lerp(0.88, 1.0, _ease_spring(self._press_rt))
        if self._press_rt >= 1.0:
            self._press_hit = None
            self._press_releasing = False
            self._press_t = 0.0
            self._press_rt = 0.0
            self._press_scale_val = 1.0
            return False
        return True

    def _circle_vis(self, key) -> float:
        """Visibility in [0,1] for `key`: 0 = collapsed at the emblem center,
        1 = settled at its slot. Drives center/scale/opacity interpolation."""
        if self._closing:
            start = self._close_from.get(key, 1.0)
            return start * (1.0 - self._close_progress.get(key, 0.0))
        if self._appear_active:
            return self._appear_progress.get(key, 0.0)
        return 1.0

    def _arm_idle(self) -> None:
        self._idle_timer.start()   # single-shot; restarts the 15s idle countdown

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._begin_close()
            return
        super().keyPressEvent(e)

    def _center(self) -> tuple[float, float]:
        return (self.width() / 2.0, self.height() / 2.0)

    def circle_geometry(self, state: str, key) -> tuple[float, float, float]:
        cx, cy = self._center()
        if state == "main":
            x, y = polar_point(cx, cy, self._ring, self._main_angles[key])
            return (x, y, self._sat_r)
        # accounts sub-ring
        sring = self._ring * 1.06   # sub-ring sits 6% further out
        if key == "back":
            x, y = polar_point(cx, cy, sring, -90.0)
            return (x, y, self._sat_r)
        angles = account_ring_angles(len(self._accounts))
        x, y = polar_point(cx, cy, sring, angles[int(key)])
        return (x, y, self._sat_r)

    def _visible_circles(self):
        out = []
        if self._state == "main":
            for key in self._main_keys:
                cx, cy, r = self.circle_geometry("main", key)
                out.append(("main", key, cx, cy, r))
        else:  # accounts sub-ring geometry
            bx, by, br = self.circle_geometry("accounts", "back")
            out.append(("accounts", "back", bx, by, br))
            for i in range(len(self._accounts)):
                cx, cy, r = self.circle_geometry("accounts", i)
                out.append(("accounts", i, cx, cy, r))
        return out

    def _hit(self, x: float, y: float):
        for (state, key, cx, cy, r) in self._visible_circles():
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                return (state, key)
        return None

    def activate_at(self, x: float, y: float) -> None:
        if self._closing:
            return
        self._arm_idle()
        hit = self._hit(x, y)
        if hit is None:
            return
        state, key = hit
        if state == "main":
            if key == "accounts":
                self.accounts_requested.emit()
            elif key == "home":
                self.home_requested.emit()
            elif key == "settings":
                self.settings_requested.emit()
            elif key == "transparent":
                self.transparent_requested.emit()
            elif key == "close":
                self._begin_close()
            elif key == "exit":
                self.exit_requested.emit()
        elif state == "accounts":
            if key == "back":
                self._state = "main"
                self._hover = None
                self.back_requested.emit()
                self.start_reveal()
            else:
                i = int(key)
                self.account_clicked.emit(self._accounts[i].account_id)
                self._launched.add(i)
                if self._all_accounts_launched():
                    self._begin_close()

    def _all_accounts_launched(self) -> bool:
        """True when no launchable account remains in the sub-ring: every entry
        is either already running or has been clicked this session. Only ever
        consulted right after a click, so opening a ring of all-running accounts
        does NOT auto-close it."""
        if not self._accounts:
            return False
        return all(a.running or i in self._launched
                   for i, a in enumerate(self._accounts))

    def mousePressEvent(self, e):
        # Activation happens on RELEASE (see mouseReleaseEvent). Track the pressed
        # spoke so it can depress while held. Accept the press so it does not
        # bubble to a parent host and so the implicit grab returns the release.
        if not self._closing and self._anim_enabled:
            hit = self._hit(e.position().x(), e.position().y())
            if hit is not None:
                self._press_hit = hit
                self._press_releasing = False
                self._press_t = 0.0
                self._press_rt = 0.0
                self._press_scale_val = 1.0
                self._kick()
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._press_hit is not None:
            self._press_releasing = True     # begin spring-back
            self._press_rt = 0.0
            self._kick()
        pos = e.position()
        self.activate_at(pos.x(), pos.y())
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._hover = self._hit(pos.x(), pos.y())
        self._arm_idle()
        self._kick()
        self.update()
        super().mouseMoveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # The dim/vignette backdrop is a SEPARATE layer (RadialDimWidget) that
        # sits behind the emblem; this widget paints only the spoke buttons, in
        # front of both the dim and the emblem (z-order: cards -> dim -> emblem
        # -> buttons). See RadialDimWidget and the two hosts (group_controller /
        # windowed_wheel) for the layering.
        if self._state == "main":
            self._paint_main(p)
        elif self._state == "accounts":
            self._paint_accounts(p)
        p.end()

    def _paint_glyph(self, p: QPainter, key, cx: float, cy: float, r: float) -> None:
        if key == "settings":
            _gear(p, cx, cy, r * 1.15)
        elif key == "close":
            _back_arrow(p, cx, cy, r * 0.55)
        elif key == "exit":
            _x_glyph(p, cx, cy, r * 0.5)
        elif key == "home":
            _window_frame(p, cx, cy, r * 0.52)
        elif key == "transparent":
            _overlay_cards(p, cx, cy, r * 0.72)
        else:   # accounts
            _person(p, cx, cy, r * 0.52)

    def _paint_main(self, p: QPainter) -> None:
        cx0, cy0 = self._center()
        settled = not self._appear_active and not self._closing
        for key in self._main_keys:
            vis = self._circle_vis(key)
            if vis <= 0.001:
                continue
            sx, sy, r = self.circle_geometry("main", key)
            icx = _lerp(cx0, sx, vis)
            icy = _lerp(cy0, sy, vis)
            hp = self._hover_progress.get(key, 0.0)
            ps = self._press_scale_val if self._press_hit == ("main", key) else 1.0
            ir = r * _lerp(0.4, 1.0, vis) * (1.0 + 0.07 * hp) * ps
            hot = self._hover == ("main", key)
            danger = (key == "exit")
            p.setOpacity(_clamp01(vis))
            if hp > 0.0:
                _focus_glow(p, icx, icy, ir, hp, danger=danger)
            _drop_shadow(p, icx, icy, ir, 1.0 + 0.6 * hp)
            _disc(p, icx, icy, ir, hot, danger=danger)
            self._paint_glyph(p, key, icx, icy, ir)
            p.setOpacity(1.0)
            if hot and settled:
                _label_pill(p, icx, icy, ir,
                            _MAIN_LABELS.get(key, key.capitalize()),
                            above=(key not in _MAIN_BOTTOM_KEYS))

    def set_accounts(self, accounts, customizations=None) -> None:
        """Switch to the accounts sub-ring and pre-render each toon portrait.

        ``customizations`` (a ToonCustomizationsManager) is optional so callers
        can supply real portrait styling after construction; backward compatible
        with ``set_accounts(accts)`` (customizations stays whatever it was)."""
        from utils.overlay.radial_portrait import render_account_portrait
        if customizations is not None:
            self._customizations = customizations
        self._accounts = list(accounts)
        self._portraits = {}
        self._launched = set()
        self._loading = set()
        d = max(1, int(round(self._sat_r * 2)))
        for a in self._accounts:
            render = render_account_portrait(
                a.game, a.toon_name, a.dna, self._customizations, d)
            self._portraits[a.account_id] = render.pixmap
            if render.status == "pending":
                self._loading.add(a.account_id)
        self._state = "accounts"
        self._hover = None
        self.start_reveal()

    def _on_pose_ready(self, dna, pose, pixmap):
        """A Rendition pose arrived. Re-render any still-pending account whose
        DNA matches (the disk cache is now warm) and repaint. No-op unless the
        accounts sub-ring is showing.

        ``pixmap is None`` is the fetcher's failure signal. Treat it as a
        definitive miss: stop the spinner (drop the id from ``_loading``) and do
        NOT re-render. Re-rendering would call ``set_dna`` again, which re-fires
        the fetch as a side effect -- so refreshing on failure would loop into a
        retry storm against the Rendition server and a never-resolving spinner.
        A later ring-open re-attempts the fetch via set_accounts / pre-warm."""
        if self._state != "accounts" or not dna:
            return
        from utils.overlay.radial_portrait import render_account_portrait
        d = max(1, int(round(self._sat_r * 2)))
        changed = False
        for a in self._accounts:
            if a.dna != dna or a.account_id not in self._loading:
                continue
            if pixmap is None:
                self._loading.discard(a.account_id)
                changed = True
                continue
            render = render_account_portrait(
                a.game, a.toon_name, a.dna, self._customizations, d)
            self._portraits[a.account_id] = render.pixmap
            if render.status != "pending":
                self._loading.discard(a.account_id)
            changed = True
        if changed:
            self.update()

    def _paint_accounts(self, p: QPainter) -> None:
        cx0, cy0 = self._center()
        sring = self._ring * 1.06
        settled = not self._appear_active and not self._closing
        # Back button
        bvis = self._circle_vis("back")
        if bvis > 0.001:
            bx0, by0, br = self.circle_geometry("accounts", "back")
            bx = _lerp(cx0, bx0, bvis); by = _lerp(cy0, by0, bvis)
            hp = self._hover_progress.get("back", 0.0)
            ps = self._press_scale_val if self._press_hit == ("accounts", "back") else 1.0
            r_eff = br * _lerp(0.4, 1.0, bvis) * (1.0 + 0.07 * hp) * ps
            hot_back = self._hover == ("accounts", "back")
            p.setOpacity(_clamp01(bvis))
            if hp > 0.0:
                _focus_glow(p, bx, by, r_eff, hp)
            _drop_shadow(p, bx, by, r_eff, 1.0 + 0.6 * hp)
            _disc(p, bx, by, r_eff, hot_back)
            _back_arrow(p, bx, by, r_eff * 0.55)
            p.setOpacity(1.0)
            if hot_back and settled:
                _label_pill(p, bx, by, r_eff, "Back", above=True)
        angles = account_ring_angles(len(self._accounts))
        for i, acct in enumerate(self._accounts):
            vis = self._circle_vis(i)
            if vis <= 0.001:
                continue
            sx, sy, r = self.circle_geometry("accounts", i)
            icx = _lerp(cx0, sx, vis); icy = _lerp(cy0, sy, vis)
            hp = self._hover_progress.get(i, 0.0)
            ps = self._press_scale_val if self._press_hit == ("accounts", i) else 1.0
            ir = r * _lerp(0.4, 1.0, vis) * (1.0 + 0.07 * hp) * ps
            hot = self._hover == ("accounts", i)
            p.setOpacity(_clamp01(vis))
            if hp > 0.0:
                _focus_glow(p, icx, icy, ir, hp)
            _drop_shadow(p, icx, icy, ir, 1.0 + 0.6 * hp)
            _account_frame(p, icx, icy, ir, hot)
            pm = self._portraits.get(acct.account_id)
            if pm is not None and not pm.isNull():
                # Portraits are pre-rendered at the resting diameter (sat_r*2);
                # only pay for a smooth rescale when the disc is actually a
                # different size (entrance/exit/hover-lift), else blit directly.
                d = max(1, int(ir * 2))
                draw = (pm if abs(d - pm.width()) <= 1
                        else pm.scaled(d, d, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
                p.drawPixmap(QPointF(icx - draw.width() / 2.0,
                                     icy - draw.height() / 2.0), draw)
            if acct.account_id in self._loading:
                _loading_spinner(p, icx, icy, ir, self._spinner_phase)
            if acct.running:
                _status_dot(p, icx, icy, ir)
            p.setOpacity(1.0)
            if hot and settled:
                name = acct.toon_name or acct.label
                lx, ly = polar_point(cx0, cy0, sring + ir + 22, angles[i])
                _label_at(p, lx, ly, name)
