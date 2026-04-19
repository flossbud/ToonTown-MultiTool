from PySide6.QtGui import QPalette, QFont, QPixmap, QPainter, QColor, QIcon, QPen, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget, QLabel
from PySide6.QtCore import Qt, QRectF
import math


# ── Icon Generators ────────────────────────────────────────────────────────

def make_chat_icon(size: int = 18) -> QIcon:
    """Draw a chat bubble icon using Qt primitives."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setBrush(QColor(255, 255, 255, 220))
    painter.setPen(Qt.NoPen)
    bubble_rect = pixmap.rect().adjusted(1, 1, -1, -4)
    painter.drawRoundedRect(bubble_rect, 3, 3)

    path = QPainterPath()
    path.moveTo(3, size - 4)
    path.lineTo(1, size - 1)
    path.lineTo(7, size - 4)
    path.closeSubpath()
    painter.drawPath(path)

    painter.setBrush(QColor(80, 80, 80, 200))
    dot_y = size // 2 - 1
    for dx in [4, size // 2, size - 5]:
        painter.drawEllipse(dx - 1, dot_y, 2, 2)

    painter.end()
    return QIcon(pixmap)


def make_refresh_icon(size: int = 14) -> QIcon:
    """Draw a circular refresh arrow using Qt primitives."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen_color = QColor(200, 200, 200)
    pen = QPen(pen_color, max(1.5, size / 10))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    margin = size * 0.15
    arc_rect = QRectF(margin, margin, size - margin * 2, size - margin * 2)
    painter.drawArc(arc_rect, 60 * 16, 300 * 16)

    angle_rad = math.radians(60)
    cx, cy = size / 2, size / 2
    r = (size - margin * 2) / 2
    tip_x = cx + r * math.cos(angle_rad)
    tip_y = cy - r * math.sin(angle_rad)

    arrow_size = size * 0.28
    path = QPainterPath()
    path.moveTo(tip_x, tip_y)
    path.lineTo(tip_x - arrow_size, tip_y - arrow_size * 0.3)
    path.lineTo(tip_x - arrow_size * 0.3, tip_y + arrow_size)
    path.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(pen_color)
    painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)


def make_mouse_icon(size: int = 16) -> QIcon:
    """Draw a computer mouse icon using Qt primitives."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    body_color = QColor(255, 255, 255, 220)
    line_color = QColor(80, 80, 80, 200)

    m = size * 0.18
    top = size * 0.08
    bot = size * 0.92
    body_rect = QRectF(m, top, size - m * 2, bot - top)
    painter.setPen(Qt.NoPen)
    painter.setBrush(body_color)
    painter.drawRoundedRect(body_rect, size * 0.3, size * 0.3)

    pen = QPen(line_color, max(1.0, size / 14))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    cx = size / 2
    painter.drawLine(int(cx), int(top + size * 0.08), int(cx), int(top + size * 0.42))

    wheel_w = size * 0.12
    wheel_h = size * 0.18
    painter.setBrush(line_color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(cx - wheel_w / 2, top + size * 0.16, wheel_w, wheel_h))

    painter.end()
    return QIcon(pixmap)


def _draw_nav_icon(size: int, color: QColor, draw_func) -> QIcon:
    """Helper: create a pixmap, set up painter, call draw_func, return icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    draw_func(painter, size, color)
    painter.end()
    return QIcon(pixmap)


def make_heart_icon(size: int = 16, color: QColor = None) -> QIcon:
    """Draw a heart icon using Qt primitives."""
    color = color or QColor("#E05252")
    def draw(p, s, c):
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        path = QPainterPath()
        # Scale parameters
        w = s * 0.8
        h = s * 0.8
        dx = (s - w) / 2
        dy = (s - h) / 2
        
        # Start at top center cleft
        path.moveTo(dx + w/2, dy + h*0.25)
        # Left curve
        path.cubicTo(dx, dy - h*0.1,  # Control 1
                     dx - w*0.1, dy + h*0.6, # Control 2
                     dx + w/2, dy + h) # Bottom point
        # Right curve
        path.cubicTo(dx + w*1.1, dy + h*0.6,
                     dx + w, dy - h*0.1,
                     dx + w/2, dy + h*0.25)
        path.closeSubpath()
        p.drawPath(path)
    return _draw_nav_icon(size, color, draw)


def make_jellybean_icon(size: int = 16, color: QColor = None) -> QIcon:
    """Draw a jellybean icon using Qt primitives."""
    color = color or QColor("#E8A838")
    def draw(p, s, c):
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        
        p.translate(s/2, s/2)
        p.rotate(30) # Tilt it like a jellybean
        
        # Draw a rounded rect (pill shape) slightly curved if possible, 
        # but a simple pill is fine for 16x16
        pill_w = s * 0.5
        pill_h = s * 0.8
        rect = QRectF(-pill_w/2, -pill_h/2, pill_w, pill_h)
        path = QPainterPath()
        path.addRoundedRect(rect, pill_w/2, pill_w/2)
        p.drawPath(path)
        
        # Add a little white highlight to make it look like a bean
        hl_w = pill_w * 0.3
        hl_h = pill_h * 0.3
        p.setBrush(QColor(255, 255, 255, 100))
        p.drawEllipse(QRectF(-pill_w*0.2, -pill_h*0.25, hl_w, hl_h))
        
        p.rotate(-30)
        p.translate(-s/2, -s/2)
    return _draw_nav_icon(size, color, draw)


def make_nav_gamepad(size: int = 22, color: QColor = None) -> QIcon:
    """Gamepad icon for Multitoon nav."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 14))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Body
        body = QRectF(s * 0.1, s * 0.25, s * 0.8, s * 0.5)
        p.drawRoundedRect(body, s * 0.18, s * 0.18)
        # D-pad (left side)
        cx, cy = s * 0.32, s * 0.5
        arm = s * 0.1
        p.drawLine(QRectF(cx - arm, cy, arm * 2, 0).topLeft(), QRectF(cx - arm, cy, arm * 2, 0).topRight())
        p.drawLine(QRectF(cx, cy - arm, 0, arm * 2).topLeft(), QRectF(cx, cy - arm, 0, arm * 2).bottomLeft())
        # Buttons (right side) — two dots
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(s * 0.62, s * 0.42, s * 0.08, s * 0.08))
        p.drawEllipse(QRectF(s * 0.72, s * 0.5, s * 0.08, s * 0.08))
    return _draw_nav_icon(size, color, draw)


def make_nav_power(size: int = 22, color: QColor = None) -> QIcon:
    """Power button icon for Launch nav."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        from PySide6.QtCore import QPointF
        pen = QPen(c, max(1.6, s / 12))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.36
        # Arc: gap at top (~80 degrees wide)
        gap = 40
        start = 90 + gap
        span = 360 - gap * 2
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                  int(start * 16), int(span * 16))
        # Vertical line up through the gap
        p.drawLine(QPointF(cx, cy - r * 0.35), QPointF(cx, cy - r * 1.18))
    return _draw_nav_icon(size, color, draw)


make_nav_rocket = make_nav_power  # alias so existing imports don't break


def make_nav_bookmark(size: int = 22, color: QColor = None) -> QIcon:
    """Bookmark/save icon for Presets nav."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 14))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.1)
        path.lineTo(s * 0.22, s * 0.85)
        path.lineTo(s * 0.5, s * 0.65)
        path.lineTo(s * 0.78, s * 0.85)
        path.lineTo(s * 0.78, s * 0.1)
        path.closeSubpath()
        p.drawPath(path)
    return _draw_nav_icon(size, color, draw)


def make_nav_gear(size: int = 22, color: QColor = None) -> QIcon:
    """Gear icon for Settings nav — 8 teeth with center hole."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        import math
        cx, cy  = s / 2.0, s / 2.0
        n_teeth = 8
        r_outer = s * 0.44
        r_inner = s * 0.30
        r_hole  = s * 0.13
        half_t  = math.pi / n_teeth * 0.6
        gear = QPainterPath()
        for i in range(n_teeth):
            base = math.radians(i * 360 / n_teeth)
            a0 = base - half_t
            a1 = base - half_t * 0.4
            a2 = base + half_t * 0.4
            a3 = base + half_t
            pt = lambda r, a: (cx + r * math.cos(a), cy + r * math.sin(a))
            if i == 0:
                gear.moveTo(*pt(r_inner, a0))
            else:
                gear.lineTo(*pt(r_inner, a0))
            gear.lineTo(*pt(r_outer, a1))
            gear.lineTo(*pt(r_outer, a2))
            gear.lineTo(*pt(r_inner, a3))
        gear.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(QRectF(cx - r_hole, cy - r_hole, r_hole * 2, r_hole * 2))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPath(gear.subtracted(hole))
    return _draw_nav_icon(size, color, draw)


def make_trash_icon(size: int = 18, color: QColor = None) -> QIcon:
    """Draw a trash can icon using Qt primitives."""
    if color is None:
        color = QColor(255, 255, 255, 220)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(color, max(1.6, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    m = size * 0.12
    w = size - 2 * m

    # Lid line
    lid_y = m + w * 0.16
    p.drawLine(int(m), int(lid_y), int(size - m), int(lid_y))

    # Lid handle
    handle_w = w * 0.34
    handle_h = w * 0.14
    hx = size / 2 - handle_w / 2
    p.drawRoundedRect(QRectF(hx, lid_y - handle_h, handle_w, handle_h), 2, 2)

    # Body (trapezoid-ish)
    body_top = lid_y + 1.5
    body_bot = size - m
    inset = w * 0.05
    body_path = QPainterPath()
    body_path.moveTo(m + inset, body_top)
    body_path.lineTo(size - m - inset, body_top)
    body_path.lineTo(size - m - inset * 3, body_bot)
    body_path.lineTo(m + inset * 3, body_bot)
    body_path.closeSubpath()
    p.drawPath(body_path)

    # Vertical lines inside body
    cx = size / 2
    line_top = body_top + (body_bot - body_top) * 0.22
    line_bot = body_bot - (body_bot - body_top) * 0.15
    for dx in [-w * 0.16, 0, w * 0.16]:
        p.drawLine(int(cx + dx), int(line_top), int(cx + dx), int(line_bot))

    p.end()
    return QIcon(pixmap)


def make_nav_keyboard(size: int = 22, color: QColor = None) -> QIcon:
    """Keyboard icon for Keymap nav."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.2, s / 16))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Keyboard body
        p.drawRoundedRect(QRectF(s*0.06, s*0.24, s*0.88, s*0.52), s*0.09, s*0.09)
        # Top row of keys
        kw, kh = s * 0.14, s * 0.13
        ky = s * 0.33
        for ki in range(4):
            kx = s * 0.13 + ki * (kw + s * 0.056)
            p.drawRoundedRect(QRectF(kx, ky, kw, kh), s*0.03, s*0.03)
        # Bottom row: two small keys + spacebar
        ky2 = s * 0.54
        for ki in range(2):
            kx = s * 0.13 + ki * (kw + s * 0.056)
            p.drawRoundedRect(QRectF(kx, ky2, kw, kh), s*0.03, s*0.03)
        p.drawRoundedRect(QRectF(s*0.39, ky2, s*0.36, kh), s*0.03, s*0.03)
    return _draw_nav_icon(size, color, draw)


def make_nav_terminal(size: int = 22, color: QColor = None) -> QIcon:
    """Terminal/console icon for Logs nav."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 14))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Terminal box
        p.drawRoundedRect(QRectF(s * 0.1, s * 0.15, s * 0.8, s * 0.7), s * 0.08, s * 0.08)
        # Prompt chevron >_
        p.drawLine(int(s * 0.22), int(s * 0.40), int(s * 0.38), int(s * 0.52))
        p.drawLine(int(s * 0.38), int(s * 0.52), int(s * 0.22), int(s * 0.64))
        # Cursor line
        p.drawLine(int(s * 0.44), int(s * 0.64), int(s * 0.62), int(s * 0.64))
    return _draw_nav_icon(size, color, draw)


def make_hint_icon(size: int = 18, color: QColor = None, active: bool = True) -> QIcon:
    """Hint '?' icon in a circle for the hint toggle button."""
    color = color or QColor(200, 200, 200)
    if not active:
        color = QColor(color.red(), color.green(), color.blue(), 80)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 12))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        margin = s * 0.12
        p.drawEllipse(QRectF(margin, margin, s - 2 * margin, s - 2 * margin))

        p.setPen(c)
        font = p.font()
        font.setPixelSize(int(s * 0.55))
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignCenter, "?")
    return _draw_nav_icon(size, color, draw)

def make_edit_icon(size: int = 18, color: QColor = None) -> QIcon:
    """Pencil / edit icon using Qt primitives."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 12))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Pencil body (angled rectangle)
        path = QPainterPath()
        path.moveTo(s * 0.65, s * 0.12)
        path.lineTo(s * 0.88, s * 0.35)
        path.lineTo(s * 0.35, s * 0.88)
        path.lineTo(s * 0.12, s * 0.65)
        path.closeSubpath()
        p.drawPath(path)
        # Tip
        p.drawLine(int(s * 0.12), int(s * 0.65), int(s * 0.08), int(s * 0.92))
        p.drawLine(int(s * 0.08), int(s * 0.92), int(s * 0.35), int(s * 0.88))
        # Eraser line
        p.drawLine(int(s * 0.56), int(s * 0.21), int(s * 0.79), int(s * 0.44))
    return _draw_nav_icon(size, color, draw)


def make_info_icon(size: int = 18, color: QColor = None) -> QIcon:
    """Info 'i' icon in a circle for the about dialog button."""
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        pen = QPen(c, max(1.4, s / 12))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Circle
        margin = s * 0.12
        p.drawEllipse(QRectF(margin, margin, s - 2 * margin, s - 2 * margin))
        # Dot on the 'i'
        dot_y = s * 0.30
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(s * 0.45, dot_y, s * 0.10, s * 0.10))
        # Stem of the 'i'
        p.setPen(pen)
        p.drawLine(int(s * 0.5), int(s * 0.45), int(s * 0.5), int(s * 0.70))
    return _draw_nav_icon(size, color, draw)


# ── Shadow Helper ──────────────────────────────────────────────────────────

def apply_card_shadow(widget, is_dark: bool, blur: float = 18, offset_y: float = 3):
    """Apply a subtle drop shadow to a widget (card, frame, etc)."""
    shadow = QGraphicsDropShadowEffect(widget)
    if is_dark:
        shadow.setColor(QColor(0, 0, 0, 90))
    else:
        shadow.setColor(QColor(0, 0, 0, 40))
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, offset_y)
    widget.setGraphicsEffect(shadow)


# ── Section Label Helper ──────────────────────────────────────────────────

def make_section_label(text: str, c: dict) -> QLabel:
    """Return a styled section header QLabel (uppercase, small, muted)."""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"font-size: 10px; font-weight: 600; color: {c['text_muted']}; "
        f"background: transparent; border: none; letter-spacing: 0.8px;"
    )
    lbl.setContentsMargins(0, 4, 0, 2)
    return lbl


# ── Smooth Progress Bar ────────────────────────────────────────────────────

class SmoothProgressBar(QWidget):
    """Progress bar painted with sub-pixel precision and rounded pill shape."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0  # 0.0 to 1.0
        self._bg_color = QColor("#141414")
        self._fill_color = QColor("#e0943a")
        self.setFixedHeight(7)
        self.setMinimumWidth(40)

    def set_progress(self, value: float):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def set_fill_color(self, hex_color: str):
        self._fill_color = QColor(hex_color)
        self.update()

    def set_bg_color(self, hex_color: str):
        self._bg_color = QColor(hex_color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        r = h / 2.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Fill
        if self._progress > 0.001:
            fill_w = self._progress * w
            # Clamp minimum to pill shape diameter so it stays rounded
            fill_w = max(fill_w, h)
            p.setBrush(self._fill_color)
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)

        p.end()


# ── Movement Set Identity Colors ───────────────────────────────────────────
# Fixed palette — consistent across light/dark themes.
# Each entry: (background, text_color)

SET_COLORS = [
    ("#4A8FE7", "#ffffff"),   # 1 — Blue
    ("#E05252", "#ffffff"),   # 2 — Red
    ("#DAA520", "#1a1a1a"),   # 3 — Yellow / Gold
    ("#4CB960", "#ffffff"),   # 4 — Green
    ("#E08640", "#ffffff"),   # 5 — Orange
    ("#C4A46C", "#1a1a1a"),   # 6 — Tan
    ("#9B6BE0", "#ffffff"),   # 7 — Purple
    ("#8B6948", "#ffffff"),   # 8 — Brown
]


def get_set_color(index: int) -> tuple:
    """Return (bg_hex, text_hex) for a movement set index (0-based)."""
    if 0 <= index < len(SET_COLORS):
        return SET_COLORS[index]
    return ("#666666", "#ffffff")


# ── Theme Colors ───────────────────────────────────────────────────────────

def get_theme_colors(is_dark: bool) -> dict:
    """Return a dict of semantic color tokens for the current theme."""
    if is_dark:
        return {
            # Backgrounds  (elevation: sidebar < app < card < card_inner)
            "bg_app":        "#1a1a1a",
            "bg_card":       "#252525",
            "bg_card_inner": "#2e2e2e",
            "bg_input":      "#1e1e1e",
            "bg_input_dark": "#141414",
            "bg_status":     "#1e1e1e",

            # Sidebar
            "sidebar_bg":       "#111111",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
            "sidebar_text":     "#aaaaaa",
            "sidebar_text_sel": "#ffffff",
            "sidebar_border":   "#2a2a2a",

            # Header
            "header_bg":     "#1a1a1a",
            "header_text":   "#ffffff",
            "header_sub":    "#888888",
            "header_accent": "#0077ff",

            # Borders
            "border_card":  "#363636",
            "border_input": "#3a3a3a",
            "border_muted": "#2e2e2e",
            "border_light": "#555555",

            # Text
            "text_primary":   "#ffffff",
            "text_secondary": "#bbbbbb",
            "text_muted":     "#888888",
            "text_disabled":  "#666666",

            # Accent — green
            "accent_green":        "#3da343",
            "accent_green_border": "#56d66a",
            "accent_green_hover":  "#4fc95c",
            "accent_green_hover_border": "#6ae87d",
            "accent_green_subtle": "#80c080",

            # Accent — blue
            "accent_blue": "#88c0d0",
            "accent_blue_btn":        "#0077ff",
            "accent_blue_btn_border": "#3399ff",
            "accent_blue_btn_hover":  "#1a88ff",

            # Accent — red
            "accent_red":        "#b34848",
            "accent_red_border": "#d95757",
            "accent_red_hover":  "#cc5e5e",
            "accent_red_hover_border": "#f06868",

            # Accent — orange (keep-alive active)
            "accent_orange":        "#c47a2a",
            "accent_orange_border": "#e0943a",
            "accent_orange_hover":  "#d48a34",

            # Status strip — success
            "status_success_bg":     "#2c3f2c",
            "status_success_text":   "#ccffcc",
            "status_success_border": "#56c856",

            # Status strip — warning
            "status_warning_bg":     "#3a2f1a",
            "status_warning_text":   "#ffcc99",
            "status_warning_border": "#ffaa00",

            # Status strip — idle
            "status_idle_bg":     "#2f2f2f",
            "status_idle_text":   "#cccccc",
            "status_idle_border": "#555555",

            # Buttons
            "btn_bg":       "#333333",
            "btn_border":   "#444444",
            "btn_hover":    "#3e3e3e",
            "btn_disabled": "#2a2a2a",
            "btn_text":     "#ffffff",

            # Dropdowns
            "dropdown_bg":          "#2e2e2e",
            "dropdown_text":        "#ffffff",
            "dropdown_border":      "#3a3a3a",
            "dropdown_list_bg":     "#1e1e1e",
            "dropdown_sel_bg":      "#3a3a3a",
            "dropdown_sel_text":    "#ffffff",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#3a3a3a",
            "toon_btn_inactive_border": "#4a4a4a",
            "toon_btn_inactive_hover":  "#444444",
            "toon_btn_inactive_hover_border": "#5a5a5a",

            # Slot accent colors (badge circles)
            "slot_1": "#5b9bf5",
            "slot_2": "#4ade80",
            "slot_3": "#f59e42",
            "slot_4": "#b07cf5",
            "slot_dim": "#2e2e2e",

            # Toon cards (floating on gradient)
            "card_toon_bg":        "#252525",
            "card_toon_border":    "#363636",
            "card_toon_active_bg": "#1e2e1e",

            # Segment status bar
            "segment_off":    "#1e1e1e",
            "segment_found":  "#363636",
            "segment_active": "#56c856",
        }
    else:
        return {
            # Backgrounds  (elevation: sidebar < app < card < card_inner)
            "bg_app":        "#f0f0f0",
            "bg_card":       "#ffffff",
            "bg_card_inner": "#f7f7f7",
            "bg_input":      "#ffffff",
            "bg_input_dark": "#e8e8e8",
            "bg_status":     "#f0f0f0",

            # Sidebar
            "sidebar_bg":       "#e2e2e2",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(0,0,0,0.07)",
            "sidebar_text":     "#777777",
            "sidebar_text_sel": "#111111",
            "sidebar_border":   "#d0d0d0",

            # Header
            "header_bg":     "#f0f0f0",
            "header_text":   "#222222",
            "header_sub":    "#888888",
            "header_accent": "#0077ff",

            # Borders
            "border_card":  "#d4d4d4",
            "border_input": "#bbbbbb",
            "border_muted": "#d0d0d0",
            "border_light": "#bbbbbb",

            # Text
            "text_primary":   "#000000",
            "text_secondary": "#444444",
            "text_muted":     "#666666",
            "text_disabled":  "#888888",

            # Accent — green
            "accent_green":        "#3da343",
            "accent_green_border": "#56d66a",
            "accent_green_hover":  "#4fc95c",
            "accent_green_hover_border": "#6ae87d",
            "accent_green_subtle": "#66aa66",

            # Accent — blue
            "accent_blue": "#5ba8c8",
            "accent_blue_btn":        "#0077ff",
            "accent_blue_btn_border": "#3399ff",
            "accent_blue_btn_hover":  "#1a88ff",

            # Accent — red
            "accent_red":        "#b34848",
            "accent_red_border": "#d95757",
            "accent_red_hover":  "#cc5e5e",
            "accent_red_hover_border": "#f06868",

            # Accent — orange (keep-alive active)
            "accent_orange":        "#c47a2a",
            "accent_orange_border": "#e0943a",
            "accent_orange_hover":  "#d48a34",

            # Status strip — success
            "status_success_bg":     "#e8f5e9",
            "status_success_text":   "#2e7d32",
            "status_success_border": "#66bb6a",

            # Status strip — warning
            "status_warning_bg":     "#fff8e1",
            "status_warning_text":   "#444444",
            "status_warning_border": "#f0b400",

            # Status strip — idle
            "status_idle_bg":     "#f0f0f0",
            "status_idle_text":   "#444444",
            "status_idle_border": "#bbbbbb",

            # Buttons
            "btn_bg":       "#e8e8e8",
            "btn_border":   "#c0c0c0",
            "btn_hover":    "#dcdcdc",
            "btn_disabled": "#eeeeee",
            "btn_text":     "#111111",

            # Dropdowns
            "dropdown_bg":          "#ffffff",
            "dropdown_text":        "#111111",
            "dropdown_border":      "#c0c0c0",
            "dropdown_list_bg":     "#f8f8f8",
            "dropdown_sel_bg":      "#e0e0e0",
            "dropdown_sel_text":    "#000000",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#e8e8e8",
            "toon_btn_inactive_border": "#c0c0c0",
            "toon_btn_inactive_hover":  "#dcdcdc",
            "toon_btn_inactive_hover_border": "#aaaaaa",

            # Slot accent colors (badge circles)
            "slot_1": "#4a8be0",
            "slot_2": "#3bc46a",
            "slot_3": "#e08a30",
            "slot_4": "#9b6be0",
            "slot_dim": "#d8d8d8",

            # Toon cards (floating on gradient)
            "card_toon_bg":        "#ffffff",
            "card_toon_border":    "#d4d4d4",
            "card_toon_active_bg": "#eaf5ea",

            # Segment status bar
            "segment_off":    "#e0e0e0",
            "segment_found":  "#c0c0c0",
            "segment_active": "#4caf50",
        }


# ── Global Stylesheets ────────────────────────────────────────────────────

DARK_THEME = """
    QWidget {
        font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 12pt;
        background-color: #1a1a1a;
        color: #e0e0e0;
    }
    QPushButton {
        background-color: #333333;
        color: white;
        border-radius: 8px;
        padding: 6px 14px;
        border: 1px solid #444444;
    }
    QPushButton:hover {
        background-color: #3e3e3e;
        border: 1px solid #555555;
    }
    QPushButton:pressed {
        background-color: #282828;
        border: 1px solid #3a3a3a;
        padding-top: 7px;
        padding-bottom: 5px;
    }
    QPushButton:disabled {
        background-color: #2a2a2a;
        color: #666666;
        border: 1px solid #333333;
    }
    QComboBox {
        background-color: #2e2e2e;
        color: white;
        border-radius: 8px;
        padding: 4px 8px;
        border: 1px solid #3a3a3a;
    }
    QComboBox QAbstractItemView {
        background-color: #1e1e1e;
        selection-background-color: #3a3a3a;
        color: white;
    }
"""

LIGHT_THEME = """
    QWidget {
        font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 12pt;
        background-color: #f0f0f0;
        color: #202020;
    }
    QPushButton {
        background-color: #e8e8e8;
        color: #111;
        border-radius: 8px;
        padding: 6px 14px;
        border: 1px solid #c0c0c0;
    }
    QPushButton:hover {
        background-color: #dcdcdc;
        border: 1px solid #aaaaaa;
    }
    QPushButton:pressed {
        background-color: #d0d0d0;
        border: 1px solid #999999;
        padding-top: 7px;
        padding-bottom: 5px;
    }
    QPushButton:disabled {
        background-color: #eeeeee;
        color: #aaaaaa;
        border: 1px solid #d0d0d0;
    }
    QComboBox {
        background-color: #ffffff;
        color: #111;
        border-radius: 8px;
        padding: 4px 8px;
        border: 1px solid #c0c0c0;
    }
    QComboBox QAbstractItemView {
        background-color: #f8f8f8;
        selection-background-color: #e0e0e0;
        color: #111;
    }
"""


def resolve_theme(settings_manager) -> str:
    user_pref = settings_manager.get("theme", "system")
    if user_pref in ("light", "dark"):
        return user_pref
    palette = QApplication.instance().palette()
    base_color = palette.color(QPalette.Base)
    return "dark" if base_color.value() < 128 else "light"


def apply_theme(app, theme: str):
    if theme == "dark":
        app.setStyleSheet(DARK_THEME)
    elif theme == "light":
        app.setStyleSheet(LIGHT_THEME)
    else:
        app.setStyleSheet("")