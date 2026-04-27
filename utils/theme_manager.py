from PySide6.QtGui import QPalette, QFont, QPixmap, QPainter, QColor, QIcon, QPen, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget, QLabel
from PySide6.QtCore import Qt, QRectF
import math

# Backward compatibility: icon generators moved to utils.icon_factory
from utils.icon_factory import *  # noqa: F401,F403

# Backward compatibility: SmoothProgressBar moved to utils.shared_widgets
from utils.shared_widgets import SmoothProgressBar  # noqa: F401


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


_APPLIED_THEME: str | None = None  # set by apply_theme(); used by is_dark_palette()


def is_dark_palette() -> bool:
    """Return True if the currently applied app theme is dark.

    Tracks the theme apply_theme() last set, because apply_theme only changes
    the Qt stylesheet -- it does NOT touch QApplication.palette(), so reading
    the palette gives the OS default (e.g. KDE Plasma dark) rather than the
    in-app theme. Falls back to inspecting the palette when no theme has been
    applied yet (early startup).
    """
    if _APPLIED_THEME == "dark":
        return True
    if _APPLIED_THEME == "light":
        return False
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Base).value() < 128


def apply_theme(app, theme: str):
    global _APPLIED_THEME
    _APPLIED_THEME = theme if theme in ("dark", "light") else None
    if theme == "dark":
        app.setStyleSheet(DARK_THEME)
    elif theme == "light":
        app.setStyleSheet(LIGHT_THEME)
    else:
        app.setStyleSheet("")