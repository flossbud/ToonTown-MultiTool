from PySide6.QtGui import QPalette, QFont, QPixmap, QPainter, QColor, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def make_chat_icon(size: int = 18) -> QIcon:
    """Draw a chat bubble icon using Qt primitives."""
    from PySide6.QtGui import QPainterPath
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Bubble body
    painter.setBrush(QColor(255, 255, 255, 220))
    painter.setPen(Qt.NoPen)
    bubble_rect = pixmap.rect().adjusted(1, 1, -1, -4)
    painter.drawRoundedRect(bubble_rect, 3, 3)

    # Tail (small triangle at bottom-left)
    path = QPainterPath()
    path.moveTo(3, size - 4)
    path.lineTo(1, size - 1)
    path.lineTo(7, size - 4)
    path.closeSubpath()
    painter.drawPath(path)

    # Three dots inside bubble
    painter.setBrush(QColor(80, 80, 80, 200))
    dot_y = size // 2 - 1
    for dx in [4, size // 2, size - 5]:
        painter.drawEllipse(dx - 1, dot_y, 2, 2)

    painter.end()
    return QIcon(pixmap)


def make_refresh_icon(size: int = 14) -> QIcon:
    """Draw a circular refresh arrow using Qt primitives — font independent."""
    from PySide6.QtGui import QPainterPath, QPen
    from PySide6.QtCore import QRectF
    import math

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

    # Draw ~300 degree arc (leaving a gap for the arrowhead)
    painter.drawArc(arc_rect, 60 * 16, 300 * 16)

    # Arrowhead at the end of the arc (~60 degrees position)
    angle_rad = math.radians(60)
    cx = size / 2
    cy = size / 2
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


def get_theme_colors(is_dark: bool) -> dict:
    """Return a dict of semantic color tokens for the current theme.
    All styling across every tab pulls from here — change a color once,
    it updates everywhere."""
    if is_dark:
        return {
            # Backgrounds
            "bg_app":        "#2c2c2c",
            "bg_card":       "#444444",
            "bg_card_inner": "#3a3a3a",
            "bg_input":      "#3a3a3a",
            "bg_input_dark": "#2a2a2a",
            "bg_status":     "#2f2f2f",

            # Borders
            "border_card":  "#555555",
            "border_input": "#666666",
            "border_muted": "#444444",
            "border_light": "#777777",

            # Text
            "text_primary":   "#ffffff",
            "text_secondary": "#bbbbbb",
            "text_muted":     "#888888",
            "text_disabled":  "#999999",

            # Accent — green (primary action, enabled state)
            "accent_green":        "#3da343",
            "accent_green_border": "#56d66a",
            "accent_green_hover":  "#4fc95c",
            "accent_green_hover_border": "#6ae87d",
            "accent_green_subtle": "#80c080",

            # Accent — blue (hover highlight)
            "accent_blue": "#88c0d0",
            "accent_blue_btn":        "#3a7abf",
            "accent_blue_btn_border": "#5599dd",
            "accent_blue_btn_hover":  "#4a8fd4",

            # Accent — red (destructive / stop)
            "accent_red":        "#b34848",
            "accent_red_border": "#d95757",
            "accent_red_hover":  "#cc5e5e",
            "accent_red_hover_border": "#f06868",

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

            # Buttons (generic)
            "btn_bg":       "#4a4a4a",
            "btn_border":   "#666666",
            "btn_hover":    "#5a5a5a",
            "btn_disabled": "#555555",
            "btn_text":     "#ffffff",

            # Dropdowns
            "dropdown_bg":          "#3a3a3a",
            "dropdown_text":        "#ffffff",
            "dropdown_border":      "#666666",
            "dropdown_list_bg":     "#2a2a2a",
            "dropdown_sel_bg":      "#555555",
            "dropdown_sel_text":    "#ffffff",

            # Toon enable button — inactive (service running, not enabled)
            "toon_btn_inactive_bg":     "#666666",
            "toon_btn_inactive_border": "#777777",
            "toon_btn_inactive_hover":  "#777777",
            "toon_btn_inactive_hover_border": "#999999",
        }
    else:
        return {
            # Backgrounds
            "bg_app":        "#f5f5f5",
            "bg_card":       "#ffffff",
            "bg_card_inner": "#f0f0f0",
            "bg_input":      "#ffffff",
            "bg_input_dark": "#eeeeee",
            "bg_status":     "#f0f0f0",

            # Borders
            "border_card":  "#cccccc",
            "border_input": "#999999",
            "border_muted": "#aaaaaa",
            "border_light": "#aaaaaa",

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

            # Accent — blue (hover highlight, same as green in light mode)
            "accent_blue": "#66aa66",
            "accent_blue_btn":        "#3a7abf",
            "accent_blue_btn_border": "#5599dd",
            "accent_blue_btn_hover":  "#4a8fd4",

            # Accent — red
            "accent_red":        "#b34848",
            "accent_red_border": "#d95757",
            "accent_red_hover":  "#cc5e5e",
            "accent_red_hover_border": "#f06868",

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

            # Buttons (generic)
            "btn_bg":       "#eeeeee",
            "btn_border":   "#aaaaaa",
            "btn_hover":    "#dddddd",
            "btn_disabled": "#e0e0e0",
            "btn_text":     "#111111",

            # Dropdowns
            "dropdown_bg":          "#ffffff",
            "dropdown_text":        "#111111",
            "dropdown_border":      "#aaaaaa",
            "dropdown_list_bg":     "#f8f8f8",
            "dropdown_sel_bg":      "#e0e0e0",
            "dropdown_sel_text":    "#000000",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#f0f0f0",
            "toon_btn_inactive_border": "#aaaaaa",
            "toon_btn_inactive_hover":  "#e8e8e8",
            "toon_btn_inactive_hover_border": "#888888",
        }


DARK_THEME = """
    QWidget {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 11.5pt;
        background-color: #2c2c2c;
        color: #e0e0e0;
    }
    QTabWidget::pane {
        border: 1px solid #555;
        border-radius: 8px;
        margin-top: -1px;
        background-color: #3e3e3e;
    }
    QTabBar::tab {
        background-color: #383838;
        color: #bbbbbb;
        padding: 6px 14px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #505050;
        color: white;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #4a4a4a;
        color: #dddddd;
    }
    QPushButton {
        background-color: #4a4a4a;
        color: white;
        border-radius: 6px;
        padding: 6px 12px;
        border: 1px solid #666;
    }
    QPushButton:hover {
        background-color: #5a5a5a;
        border: 1px solid #80c080;
    }
    QComboBox {
        background-color: #4a4a4a;
        color: white;
        border-radius: 6px;
        padding: 4px 8px;
        border: 1px solid #666;
    }
    QComboBox QAbstractItemView {
        background-color: #3a3a3a;
        selection-background-color: #5a5a5a;
        color: white;
    }
"""

LIGHT_THEME = """
    QWidget {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 11.5pt;
        background-color: #f5f5f5;
        color: #202020;
    }
    QTabWidget::pane {
        border: 1px solid #bbb;
        border-radius: 8px;
        margin-top: -1px;
        background-color: #ffffff;
    }
    QTabBar::tab {
        background-color: #e8e8e8;
        color: #222;
        padding: 6px 14px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #ffffff;
        color: black;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #dddddd;
        color: black;
    }
    QPushButton {
        background-color: #eeeeee;
        color: #111;
        border-radius: 6px;
        padding: 6px 12px;
        border: 1px solid #aaa;
    }
    QPushButton:hover {
        background-color: #dddddd;
        border: 1px solid #66aa66;
    }
    QComboBox {
        background-color: #ffffff;
        color: #111;
        border-radius: 6px;
        padding: 4px 8px;
        border: 1px solid #aaa;
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