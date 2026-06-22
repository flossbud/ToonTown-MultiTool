"""Interactive radial menu widget for the emblem overlay.

Paints a soft radial vignette plus a ring of azure circles around the emblem
center and routes clicks to intent signals. The main ring has two variants
(selected by the ``variant`` ctor arg): transparent mode (Accounts, Window,
Settings, Back, Exit) and windowed mode (Accounts, Float, Back). Clicking
Accounts opens the accounts sub-ring (Back plus up to 8 recent accounts rendered
as their toon's customized portrait, with a green dot for a running account). Supports a staggered left-to-right pop-in reveal, hover labels,
Esc-to-close, and a 15s idle auto-hide. Geometry comes from
utils/radial_menu_layout.py; account portraits from utils/overlay/radial_portrait.py.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import (QPainter, QColor, QBrush, QPen, QLinearGradient,
                           QRadialGradient, QPainterPath, QFont, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils.radial_menu_layout import (MAIN_RING_ANGLES, WINDOWED_RING_ANGLES,
                                       account_ring_angles, polar_point)

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


# --- glyph + disc painters (azure theme matching the emblem) ------------------

def _disc(p: QPainter, cx: float, cy: float, r: float, hot: bool = False,
          danger: bool = False) -> None:
    gmul = 2.0 if hot else 1.7
    a0 = 210 if hot else 150
    if danger:
        # Red palette for the Exit (quit-the-app) spoke.
        gi, gm, go = (255, 70, 60), (225, 45, 40), (190, 25, 25)
        face = ((QColor(255, 110, 96), QColor(225, 55, 50)) if hot
                else (QColor(255, 92, 80), QColor(208, 40, 40)))
    else:
        gi, gm, go = (0, 185, 249), (0, 150, 245), (0, 120, 239)
        face = ((QColor(70, 205, 255), QColor(0, 140, 255)) if hot
                else (QColor(0, 185, 249), QColor(0, 119, 239)))
    glow = QRadialGradient(QPointF(cx, cy), r * gmul)
    glow.setColorAt(0.0, QColor(gi[0], gi[1], gi[2], a0))
    glow.setColorAt(0.55, QColor(gm[0], gm[1], gm[2], 90 if hot else 70))
    glow.setColorAt(1.0, QColor(go[0], go[1], go[2], 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(cx, cy), r * gmul, r * gmul)
    p.setBrush(QColor(10, 12, 16))
    p.drawEllipse(QPointF(cx, cy), r + 3, r + 3)
    g = QLinearGradient(cx, cy - r, cx, cy + r)
    g.setColorAt(0.0, face[0]); g.setColorAt(1.0, face[1])
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(cx, cy), r, r)


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
    gmul = 2.0 if hot else 1.7
    glow = QRadialGradient(QPointF(cx, cy), r * gmul)
    a0 = 210 if hot else 150
    glow.setColorAt(0.0, QColor(0, 185, 249, a0))
    glow.setColorAt(0.55, QColor(0, 150, 245, 90 if hot else 70))
    glow.setColorAt(1.0, QColor(0, 120, 239, 0))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(cx, cy), r * gmul, r * gmul)
    p.setBrush(QColor(10, 12, 16))
    p.drawEllipse(QPointF(cx, cy), r + 2, r + 2)


def _label_at(p: QPainter, cx: float, cy: float, text: str) -> None:
    f = QFont("DejaVu Sans"); f.setPixelSize(18); f.setBold(True); p.setFont(f)
    fm = p.fontMetrics(); tw = fm.horizontalAdvance(text)
    pad = 10; pw = tw + pad * 2; ph = fm.height() + 8
    px = cx - pw / 2; py = cy - ph / 2
    p.setPen(Qt.NoPen); p.setBrush(QColor(12, 16, 24, 238))
    p.drawRoundedRect(QRectF(px, py, pw, ph), ph / 2, ph / 2)
    p.setPen(QColor(235, 242, 250))
    p.drawText(QRectF(px, py, pw, ph), Qt.AlignCenter, text)


def _label_pill(p: QPainter, cx: float, cy: float, r: float, text: str, above: bool) -> None:
    f = QFont("DejaVu Sans"); f.setPixelSize(18); f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics(); tw = fm.horizontalAdvance(text)
    pad = 10; pw = tw + pad * 2; ph = fm.height() + 8
    px = cx - pw / 2
    py = (cy - r - 8 - ph) if above else (cy + r + 8)
    p.setPen(Qt.NoPen); p.setBrush(QColor(12, 16, 24, 235))
    p.drawRoundedRect(QRectF(px, py, pw, ph), ph / 2, ph / 2)
    p.setPen(QColor(235, 242, 250))
    p.drawText(QRectF(px, py, pw, ph), Qt.AlignCenter, text)


class RadialMenuWidget(QWidget):
    accounts_requested = Signal()
    home_requested = Signal()
    settings_requested = Signal()
    transparent_requested = Signal()
    close_requested = Signal()
    exit_requested = Signal()
    back_requested = Signal()
    account_clicked = Signal(str)

    _REVEAL_STEP_MS = 35
    _IDLE_MS = 15000

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
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._reveal_active = False
        self._revealed = set()
        self._reveal_order_keys = []
        self._reveal_idx = 0
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(self._REVEAL_STEP_MS)
        self._reveal_timer.timeout.connect(self._reveal_tick)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self._IDLE_MS)
        self._idle_timer.timeout.connect(self.close_requested.emit)

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
        """Begin the staggered left-to-right pop-in for the current state."""
        self._reveal_order_keys = self.reveal_order(self._state)
        self._revealed = set()
        self._reveal_idx = 0
        self._reveal_active = True
        self._reveal_timer.start()
        self._arm_idle()
        self.update()

    def _reveal_tick(self) -> None:
        if self._reveal_idx >= len(self._reveal_order_keys):
            self._reveal_timer.stop()
            self._reveal_active = False
            self.update()
            return
        self._revealed.add(self._reveal_order_keys[self._reveal_idx])
        self._reveal_idx += 1
        self.update()

    def _shown(self, key) -> bool:
        """True if ``key`` should paint now (always, unless a reveal is gating it)."""
        return (not self._reveal_active) or (key in self._revealed)

    def _arm_idle(self) -> None:
        self._idle_timer.start()   # single-shot; restarts the 15s idle countdown

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_requested.emit()
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
                self.close_requested.emit()
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
                # Once every shown account is launched (just-clicked) or already
                # running, there's nothing left to do here -> dismiss the whole
                # radial so the user can jump straight into the games.
                if self._all_accounts_launched():
                    self.close_requested.emit()

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
        # Activation happens on RELEASE (see mouseReleaseEvent). Accept the press
        # so it does not bubble to a parent host (the windowed wheel dismisses on
        # its own presses) and so the implicit grab returns the release here.
        e.accept()

    def mouseReleaseEvent(self, e):
        pos = e.position()
        self.activate_at(pos.x(), pos.y())
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._hover = self._hit(pos.x(), pos.y())
        self._arm_idle()
        self.update()
        super().mouseMoveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # Soft radial dim behind the circles (NOT a sharp rectangle): it darkens
        # the emblem + satellites and fades to fully transparent before the
        # surface edge, so nothing hard-edged is painted. (True blur of the live
        # windows behind an override-redirect overlay is not feasible; this
        # radial vignette is the practical substitute.)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = min(self.width(), self.height()) / 2.0
        if radius > 0:
            dim = QRadialGradient(QPointF(cx, cy), radius)
            dim.setColorAt(0.0, QColor(8, 10, 16, 150))
            dim.setColorAt(0.55, QColor(8, 10, 16, 150))
            dim.setColorAt(0.88, QColor(8, 10, 16, 0))
            dim.setColorAt(1.0, QColor(8, 10, 16, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(dim))
            p.drawEllipse(QPointF(cx, cy), radius, radius)
        if self._state == "main":
            self._paint_main(p)
        elif self._state == "accounts":
            self._paint_accounts(p)
        p.end()

    def _paint_main(self, p: QPainter) -> None:
        for key in self._main_keys:
            if not self._shown(key):
                continue
            cx, cy, r = self.circle_geometry("main", key)
            hot = self._hover == ("main", key)
            _disc(p, cx, cy, r, hot, danger=(key == "exit"))   # Exit = red disc
            if key == "settings":
                _gear(p, cx, cy, r * 1.15)
            elif key == "close":   # labelled "Back": dismiss the ring (one level up)
                _back_arrow(p, cx, cy, r * 0.55)
            elif key == "exit":
                _x_glyph(p, cx, cy, r * 0.5)
            elif key == "home":
                _window_frame(p, cx, cy, r * 0.52)
            elif key == "transparent":
                _overlay_cards(p, cx, cy, r * 0.72)
            else:  # accounts
                _person(p, cx, cy, r * 0.52)
            if hot:
                _label_pill(p, cx, cy, r, _MAIN_LABELS.get(key, key.capitalize()),
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
        d = max(1, int(round(self._sat_r * 2)))
        for a in self._accounts:
            self._portraits[a.account_id] = render_account_portrait(
                a.game, a.toon_name, a.dna, self._customizations, d)
        self._state = "accounts"
        self._hover = None
        self.start_reveal()

    def _paint_accounts(self, p: QPainter) -> None:
        cx, cy = self._center()
        sring = self._ring * 1.06   # sub-ring sits 6% further out
        if self._shown("back"):
            bx, by, br = self.circle_geometry("accounts", "back")
            hot_back = self._hover == ("accounts", "back")
            _disc(p, bx, by, br, hot_back)
            _back_arrow(p, bx, by, br * 0.55)
            if hot_back:
                _label_pill(p, bx, by, br, "Back", above=True)
        angles = account_ring_angles(len(self._accounts))
        for i, acct in enumerate(self._accounts):
            if not self._shown(i):
                continue
            cxi, cyi, r = self.circle_geometry("accounts", i)
            hot = self._hover == ("accounts", i)
            _account_frame(p, cxi, cyi, r, hot)
            pm = self._portraits.get(acct.account_id)
            if pm is not None and not pm.isNull():
                p.drawPixmap(QPointF(cxi - pm.width() / 2.0, cyi - pm.height() / 2.0), pm)
            if acct.running:
                _status_dot(p, cxi, cyi, r)
            if hot:
                name = acct.toon_name or acct.label
                lx, ly = polar_point(cx, cy, sring + r + 22, angles[i])
                _label_at(p, lx, ly, name)
