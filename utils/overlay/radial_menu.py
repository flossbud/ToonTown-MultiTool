"""Interactive radial menu widget for the emblem overlay (main ring).

Paints a dim scrim plus a ring of azure circles around the emblem center and
routes clicks to intent signals. The accounts sub-ring (set_accounts / accounts
state) and the open animation / Esc / auto-hide are added by later tasks; this
module defines the geometry, hit-testing, painting, and signals for the MAIN
ring (Accounts, Home, Settings, Close).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import (QPainter, QColor, QBrush, QPen, QLinearGradient,
                           QRadialGradient, QPainterPath, QFont, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils.radial_menu_layout import MAIN_RING_ANGLES, account_ring_angles, polar_point

_MAIN_KEYS = ("accounts", "home", "settings", "close")


# --- glyph + disc painters (azure theme matching the emblem) ------------------

def _disc(p: QPainter, cx: float, cy: float, r: float, hot: bool = False) -> None:
    gmul = 2.0 if hot else 1.7
    glow = QRadialGradient(QPointF(cx, cy), r * gmul)
    a0 = 210 if hot else 150
    glow.setColorAt(0.0, QColor(0, 185, 249, a0))
    glow.setColorAt(0.55, QColor(0, 150, 245, 90 if hot else 70))
    glow.setColorAt(1.0, QColor(0, 120, 239, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(cx, cy), r * gmul, r * gmul)
    p.setBrush(QColor(10, 12, 16))
    p.drawEllipse(QPointF(cx, cy), r + 3, r + 3)
    g = QLinearGradient(cx, cy - r, cx, cy + r)
    if hot:
        g.setColorAt(0.0, QColor(70, 205, 255)); g.setColorAt(1.0, QColor(0, 140, 255))
    else:
        g.setColorAt(0.0, QColor(0, 185, 249)); g.setColorAt(1.0, QColor(0, 119, 239))
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


def _home(p: QPainter, cx: float, cy: float, r: float) -> None:
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255))
    roof = QPainterPath()
    roof.moveTo(cx, cy - r * 0.85); roof.lineTo(cx + r * 0.95, cy - r * 0.02); roof.lineTo(cx - r * 0.95, cy - r * 0.02)
    roof.closeSubpath(); p.drawPath(roof)
    bw = r * 1.15; bh = r * 0.85
    p.drawRect(QRectF(cx - bw / 2, cy - r * 0.05, bw, bh))
    p.setBrush(QColor(0, 140, 243))
    dw = bw * 0.30; dh = bh * 0.62
    p.drawRect(QRectF(cx - dw / 2, cy + bh - dh - r * 0.05, dw, dh))


def _close_x(p: QPainter, cx: float, cy: float, r: float) -> None:
    s = r * 0.46
    pen = QPen(QColor(255, 255, 255)); pen.setWidthF(r * 0.22); pen.setCapStyle(Qt.RoundCap)
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
    close_requested = Signal()
    back_requested = Signal()
    account_clicked = Signal(str)

    _REVEAL_STEP_MS = 35
    _IDLE_MS = 15000

    def __init__(self, emblem_diameter: float, customizations=None, parent=None):
        super().__init__(parent)
        self._emblem_dia = float(emblem_diameter)
        self._sat_r = self._emblem_dia * 0.40 / 2.0
        self._ring = self._emblem_dia / 2.0 + 16.0 + self._sat_r
        self._customizations = customizations
        self._state = "main"
        self._hover = None          # (state, key) or None
        self._accounts = []         # list[RingAccount], populated in Task 8
        self._portraits = {}        # account_id -> circular QPixmap (set in set_accounts)
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
            keys = list(_MAIN_KEYS)
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
            x, y = polar_point(cx, cy, self._ring, MAIN_RING_ANGLES[key])
            return (x, y, self._sat_r)
        # accounts sub-ring (geometry usable once _accounts is set in Task 8)
        sring = self._ring * 1.06
        if key == "back":
            x, y = polar_point(cx, cy, sring, -90.0)
            return (x, y, self._sat_r)
        angles = account_ring_angles(len(self._accounts))
        x, y = polar_point(cx, cy, sring, angles[int(key)])
        return (x, y, self._sat_r)

    def _visible_circles(self):
        out = []
        if self._state == "main":
            for key in _MAIN_KEYS:
                cx, cy, r = self.circle_geometry("main", key)
                out.append(("main", key, cx, cy, r))
        else:  # accounts (Task 8 paints these; geometry available now)
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
            elif key == "close":
                self.close_requested.emit()
        elif state == "accounts":
            if key == "back":
                self._state = "main"
                self._hover = None
                self.back_requested.emit()
                self.start_reveal()
            else:
                self.account_clicked.emit(self._accounts[int(key)].account_id)

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
        p.fillRect(self.rect(), QColor(8, 10, 16, 120))   # dim scrim
        if self._state == "main":
            self._paint_main(p)
        elif self._state == "accounts":
            self._paint_accounts(p)
        p.end()

    def _paint_main(self, p: QPainter) -> None:
        for key in _MAIN_KEYS:
            if not self._shown(key):
                continue
            cx, cy, r = self.circle_geometry("main", key)
            hot = self._hover == ("main", key)
            _disc(p, cx, cy, r, hot)
            if key == "settings":
                _gear(p, cx, cy, r * 1.15)
            elif key == "close":
                _close_x(p, cx, cy, r * 0.55)
            elif key == "home":
                _home(p, cx, cy, r * 0.52)
            else:  # accounts
                _person(p, cx, cy, r * 0.52)
            if hot:
                _label_pill(p, cx, cy, r, key.capitalize(), above=(key != "close"))

    def set_accounts(self, accounts) -> None:
        """Switch to the accounts sub-ring and pre-render each toon portrait."""
        from utils.overlay.radial_portrait import render_account_portrait
        self._accounts = list(accounts)
        self._portraits = {}
        d = max(1, int(round(self._sat_r * 2)))
        for a in self._accounts:
            self._portraits[a.account_id] = render_account_portrait(
                a.game, a.toon_name, a.dna, self._customizations, d)
        self._state = "accounts"
        self._hover = None
        self.start_reveal()

    def _paint_accounts(self, p: QPainter) -> None:
        cx, cy = self._center()
        sring = self._ring * 1.06
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
            if hot:
                name = acct.toon_name or acct.label
                lx, ly = polar_point(cx, cy, sring + r + 22, angles[i])
                _label_at(p, lx, ly, name)
