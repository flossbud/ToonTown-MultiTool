from __future__ import annotations

from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QPen, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF
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


def make_click_sync_icon(size: int = 14, color=None) -> QIcon:
    """Physical mouse: rounded body, top split line, scroll wheel.
    Stateless: callers pass the palette color (hex str or QColor)."""
    if color is None:
        color = QColor(255, 255, 255, 220)
    elif isinstance(color, str):
        color = QColor(color)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(color, max(1.0, size / 10.0))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    body = QRectF(size * 0.25, size * 0.10, size * 0.50, size * 0.80)
    painter.drawRoundedRect(body, size * 0.25, size * 0.25)
    # Top split line down to the wheel.
    painter.drawLine(QPointF(size * 0.50, size * 0.10),
                     QPointF(size * 0.50, size * 0.34))
    # Scroll wheel: a short thick rounded stroke.
    wheel = QPen(color, max(1.5, size / 7.0), Qt.SolidLine, Qt.RoundCap)
    painter.setPen(wheel)
    painter.drawLine(QPointF(size * 0.50, size * 0.32),
                     QPointF(size * 0.50, size * 0.46))

    painter.end()
    return QIcon(pixmap)


def make_click_sync_warning_icon(size: int = 14, color=None) -> QIcon:
    """Triangle-exclamation for the click sync error state."""
    if color is None:
        color = QColor(255, 255, 255, 230)
    elif isinstance(color, str):
        color = QColor(color)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(color, max(1.0, size / 10.0))
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    tri = QPainterPath()
    tri.moveTo(size * 0.50, size * 0.08)
    tri.lineTo(size * 0.93, size * 0.86)
    tri.lineTo(size * 0.07, size * 0.86)
    tri.closeSubpath()
    painter.drawPath(tri)

    bang = QPen(color, max(1.4, size / 8.0), Qt.SolidLine, Qt.RoundCap)
    painter.setPen(bang)
    painter.drawLine(QPointF(size * 0.50, size * 0.36),
                     QPointF(size * 0.50, size * 0.62))
    painter.drawPoint(QPointF(size * 0.50, size * 0.76))

    painter.end()
    return QIcon(pixmap)


def make_refresh_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Draw a circular refresh arrow using Qt primitives."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen_color = color or QColor(200, 200, 200)
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


def make_stop_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Draw a filled square stop icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    fill = color or QColor(220, 220, 220)
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill)
    # Centred square at ~70% of canvas.
    inset = size * 0.18
    painter.drawRect(QRectF(inset, inset, size - inset * 2, size - inset * 2))
    painter.end()
    return QIcon(pixmap)


def make_play_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Draw a right-facing triangle play icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    fill = color or QColor(220, 220, 220)
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill)

    # Equilateral triangle pointing right, optical-centred (shifted ~1 px
    # rightward to compensate for the visual weight bias of triangles).
    inset = size * 0.22
    path = QPainterPath()
    path.moveTo(inset + size * 0.05, inset)
    path.lineTo(inset + size * 0.05, size - inset)
    path.lineTo(size - inset + size * 0.05, size / 2)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def make_save_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Draw a floppy-disk save icon (square body + notched top corner +
    label rectangle)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    fg = color or QColor(220, 220, 220)
    pen = QPen(fg, max(1.0, size / 14))
    pen.setJoinStyle(Qt.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    inset = size * 0.14
    # Outer body with a small notch in the top-right corner.
    notch = size * 0.20
    body = QPainterPath()
    body.moveTo(inset, inset)
    body.lineTo(size - inset - notch, inset)
    body.lineTo(size - inset, inset + notch)
    body.lineTo(size - inset, size - inset)
    body.lineTo(inset, size - inset)
    body.closeSubpath()
    painter.drawPath(body)

    # Inner label rectangle (bottom half).
    label_top = size * 0.55
    label_inset = size * 0.28
    painter.drawRect(QRectF(label_inset, label_top, size - label_inset * 2, size * 0.30))
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


def make_lightning_icon(size: int = 14, color: QColor | None = None) -> QIcon:
    """Draw a stylised lightning bolt for the keep-alive toggle."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    fill = color or QColor(220, 220, 220)
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill)

    # Classic zigzag bolt traced through 6 points. Coordinates are in
    # normalized 0..1 space and scaled to `size`; tuned so the bolt
    # reads at 14 px (the default for the Multitoon icon buttons).
    norm_points = [
        (0.55, 0.05),
        (0.20, 0.55),
        (0.45, 0.55),
        (0.35, 0.95),
        (0.80, 0.40),
        (0.55, 0.40),
    ]
    path = QPainterPath()
    px, py = norm_points[0]
    path.moveTo(px * size, py * size)
    for nx, ny in norm_points[1:]:
        path.lineTo(nx * size, ny * size)
    path.closeSubpath()
    painter.drawPath(path)

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


def make_x_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Paint an X glyph into a QPixmap and return it as a QIcon.

    Bypasses QPushButton text rendering, which is necessary on KDE Breeze
    (Wayland): a small button with text '×' elides the glyph and renders
    empty. Painting into a pixmap and using setIcon() sidesteps the whole
    style / elide / font / DPI pipeline, so the X is always visible.
    """
    if color is None:
        color = QColor("#e8e8f0")
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    inset = max(2, size // 4)
    p.drawLine(inset, inset, size - inset, size - inset)
    p.drawLine(size - inset, inset, inset, size - inset)
    p.end()
    return QIcon(pix)


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


def make_help_icon(size: int = 14, color: QColor = None) -> QIcon:
    """Help '?' icon for the per-slot Keep-Alive discovery affordance.

    Bare '?' glyph — no enclosing circle. At per-slot button sizes
    (~14px) the sidebar hint toggle's '?'-in-circle didn't read as a
    question mark next to a filled chat bubble: the ring + tiny '?'
    fought for legibility. Dropping the circle and scaling the '?' to
    fill the canvas (~chat-bubble extent) with bold weight matches the
    chat icon's perceived mass. Kept as a separate function from
    make_hint_icon (which still renders the ringed glyph at 40px) so
    each can tune for its own size class without a shared regression.
    """
    color = color or QColor(200, 200, 200)
    def draw(p, s, c):
        # Just the glyph — no circle. At 14px the outlined circle had to
        # hold so much detail (ring + tiny "?") that the "?" itself never
        # read as legibly as the chat bubble next to it. Dropping the
        # circle and scaling the "?" to fill the icon canvas (~chat-bubble
        # extent) gets the help button to "I see a question mark" at a
        # glance, while bold weight balances the chat bubble's filled mass.
        p.setPen(c)
        font = p.font()
        font.setPixelSize(int(s * 0.95))
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


# ── v2 badge / nav icons ─────────────────────────────────────────────────────

def _v2_pen(color, size: int) -> QPen:
    pen = QPen(color if color is not None else QColor("#ffffff"),
               max(1.6, size * 2.2 / 24))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _v2_canvas(size: int):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    return pm, p


def make_sliders_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Three vertical slider tracks with offset crossbars (Appearance badge)."""
    pm, p = _v2_canvas(size)
    p.setPen(_v2_pen(color, size))
    s = size / 24.0
    for x, bar_y in ((4, 14), (12, 8), (20, 16)):
        p.drawLine(int(x * s), int(3 * s), int(x * s), int(21 * s))
        p.drawLine(int((x - 3) * s), int(bar_y * s), int((x + 3) * s), int(bar_y * s))
    p.end()
    return QIcon(pm)


def make_download_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Down arrow into a tray (Updates badge)."""
    pm, p = _v2_canvas(size)
    p.setPen(_v2_pen(color, size))
    s = size / 24.0
    p.drawLine(int(12 * s), int(3 * s), int(12 * s), int(15 * s))
    p.drawLine(int(7 * s), int(10 * s), int(12 * s), int(15 * s))
    p.drawLine(int(17 * s), int(10 * s), int(12 * s), int(15 * s))
    path = QPainterPath()
    path.moveTo(3 * s, 15 * s)
    path.lineTo(3 * s, 19 * s)
    path.quadTo(3 * s, 21 * s, 5 * s, 21 * s)
    path.lineTo(19 * s, 21 * s)
    path.quadTo(21 * s, 21 * s, 21 * s, 19 * s)
    path.lineTo(21 * s, 15 * s)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def make_activity_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Heartbeat polyline (Diagnostics badge)."""
    pm, p = _v2_canvas(size)
    p.setPen(_v2_pen(color, size))
    s = size / 24.0
    pts = [(2, 12), (6, 12), (9, 3), (15, 21), (18, 12), (22, 12)]
    for a, b in zip(pts, pts[1:]):
        p.drawLine(int(a[0] * s), int(a[1] * s), int(b[0] * s), int(b[1] * s))
    p.end()
    return QIcon(pm)


def make_database_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Cylinder database (Storage badge)."""
    pm, p = _v2_canvas(size)
    p.setPen(_v2_pen(color, size))
    s = size / 24.0
    p.drawEllipse(QRectF(3 * s, 2 * s, 18 * s, 6 * s))
    for y in (12, 19):
        path = QPainterPath()
        path.moveTo(3 * s, (y - 7) * s)
        path.lineTo(3 * s, y * s)
        path.arcTo(QRectF(3 * s, (y - 3) * s, 18 * s, 6 * s), 180, 180)
        path.lineTo(21 * s, (y - 7) * s)
        p.drawPath(path)
    p.end()
    return QIcon(pm)


def make_wrench_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Wrench (Advanced nav pill)."""
    pm, p = _v2_canvas(size)
    p.setPen(_v2_pen(color, size))
    s = size / 24.0
    path = QPainterPath()
    path.moveTo(14.7 * s, 6.3 * s)
    path.lineTo(17.7 * s, 9.3 * s)
    path.lineTo(21.4 * s, 5.6 * s)
    path.arcTo(QRectF(9 * s, 2 * s, 12 * s, 12 * s), 60, 200)
    path.lineTo(5.6 * s, 21.4 * s)
    path.quadTo(4 * s, 23 * s, 2.6 * s, 21.4 * s)
    path.quadTo(1 * s, 20 * s, 2.6 * s, 18.4 * s)
    path.lineTo(11 * s, 10 * s)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def make_radio_waves_icon(size: int = 20, color: QColor | None = None) -> QIcon:
    """Center dot + concentric broadcast arcs (Features nav pill)."""
    pm, p = _v2_canvas(size)
    pen = _v2_pen(color, size)
    p.setPen(pen)
    s = size / 24.0
    p.setBrush(pen.color())
    p.drawEllipse(QRectF(10.5 * s, 10.5 * s, 3 * s, 3 * s))
    p.setBrush(Qt.NoBrush)
    for r, span in ((6, 70), (10, 70)):
        rect = QRectF((12 - r) * s, (12 - r) * s, 2 * r * s, 2 * r * s)
        p.drawArc(rect, (180 - span // 2) * 16, span * 16)
        p.drawArc(rect, (0 - span // 2) * 16, span * 16)
    p.end()
    return QIcon(pm)


def make_copy_icon(size: int = 12, color: QColor | None = None) -> QIcon:
    """Lucide 'copy': front rect (9,9,13,13) over a back sheet path."""
    color = color or QColor("#ffffff")
    pm, p = _v2_canvas(size)
    s = size / 24.0
    pen = QPen(color, max(1.0, 2 * s))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(9 * s, 9 * s, 13 * s, 13 * s), 2 * s, 2 * s)
    path = QPainterPath(QPointF(5 * s, 15 * s))
    path.lineTo(4 * s, 15 * s)
    path.quadTo(2 * s, 15 * s, 2 * s, 13 * s)
    path.lineTo(2 * s, 4 * s)
    path.quadTo(2 * s, 2 * s, 4 * s, 2 * s)
    path.lineTo(13 * s, 2 * s)
    path.quadTo(15 * s, 2 * s, 15 * s, 4 * s)
    path.lineTo(15 * s, 5 * s)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def make_pause_icon(size: int = 11, color: QColor | None = None) -> QIcon:
    """Two 5x16 rounded bars (the follow-state icon in the Logs console)."""
    color = color or QColor("#ffffff")
    pm, p = _v2_canvas(size)
    s = size / 24.0
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    for x in (5, 14):
        p.drawRoundedRect(QRectF(x * s, 4 * s, 5 * s, 16 * s), 1.5 * s, 1.5 * s)
    p.end()
    return QIcon(pm)


def make_arrow_down_icon(size: int = 10, color: QColor | None = None) -> QIcon:
    """Straight-down arrow (jump-to-live pill), 3px stroke in the viewBox."""
    color = color or QColor("#ffffff")
    pm, p = _v2_canvas(size)
    s = size / 24.0
    pen = QPen(color, max(1.0, 3 * s))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(12 * s, 4 * s), QPointF(12 * s, 20 * s))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(5 * s, 13 * s))
    path.lineTo(12 * s, 20 * s)
    path.lineTo(19 * s, 13 * s)
    p.drawPath(path)
    p.end()
    return QIcon(pm)
