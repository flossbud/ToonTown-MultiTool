from PySide6.QtGui import QPalette, QFont, QPixmap, QPainter, QColor, QIcon, QPen, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget, QLabel
from PySide6.QtCore import Qt, QRectF
import math

# Backward compatibility: icon generators moved to utils.icon_factory
from utils.icon_factory import *  # noqa: F401,F403

# Backward compatibility: SmoothProgressBar moved to utils.shared_widgets
from utils.shared_widgets import SmoothProgressBar  # noqa: F401


# ── Typography Scale ──────────────────────────────────────────────────────
# Semantic font-size roles. Use font_role(name) instead of inline px values.
# Sizes chosen to match the existing visual hierarchy used in the header,
# tab content, and small badges; tweak here to rescale globally.

TYPOGRAPHY = {
    "display": 22,   # large, attention-grabbing (e.g. empty-state headlines)
    "title":   17,   # section titles, the app header title
    "body":    13,   # default content text
    "label":   11,   # small labels, version badge, status chips
    "caption": 10,   # micro labels, status pills, footnotes
}


def font_role(role: str) -> int:
    """Return the px size for a semantic typography role.

    Unknown roles fall back to "body" so a typo never produces 0px text.
    """
    return TYPOGRAPHY.get(role, TYPOGRAPHY["body"])


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
            "bg_app":        "#1a1a1f",
            "bg_card":       "#2a2a30",
            "bg_card_inner": "#2f2f36",
            "bg_input":      "#1e1e23",
            "bg_input_dark": "#141418",
            "bg_status":     "#1e1e23",

            # Sidebar
            "sidebar_bg":       "#131316",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
            "sidebar_text":     "#a8a8b0",
            "sidebar_text_sel": "#ffffff",
            "sidebar_border":   "#2c2c33",

            # Header
            "header_bg":     "#1a1a1f",
            "header_text":   "#e8e8ed",
            "header_accent": "#3a6dd8",

            # Borders
            "border_card":  "#35353c",
            "border_input": "#3a3a42",
            "border_muted": "#2c2c33",
            "border_light": "#55555c",

            # Text
            "text_primary":   "#e8e8ed",
            "text_secondary": "#c8c8d0",
            "text_muted":     "#888890",
            "text_disabled":  "#5c5c64",

            # On-accent text/icon — universal pair for every bright accent surface
            # below. Slate-900 clears AA against green-400/blue-400/red-400/violet-400.
            "text_on_accent": "#0f172a",

            # Accent — green (text-bearing surface, e.g. Enable button)
            # Pairs with text_on_accent. green-400 / 9.7:1 vs text_on_accent (AAA).
            "accent_green":        "#4ade80",
            "accent_green_border": "#86efac",
            "accent_green_hover":  "#22c55e",
            "accent_green_hover_border": "#4ade80",
            "accent_green_subtle": "#80c080",

            # Accent — blue (text-bearing surface, e.g. Set selector)
            # Pairs with text_on_accent. blue-400 / 6.7:1 (AA, near-AAA).
            "accent_blue": "#88c0d0",
            "accent_blue_btn":        "#60a5fa",
            "accent_blue_btn_border": "#93c5fd",
            "accent_blue_btn_hover":  "#3b82f6",

            # Accent — red (text-bearing surface, e.g. Stop Service)
            # Pairs with text_on_accent. red-400 / 6.3:1 (AA).
            "accent_red":        "#f87171",
            "accent_red_border": "#fca5a5",
            "accent_red_hover":  "#ef4444",
            "accent_red_hover_border": "#f87171",

            # Accent — orange (keep-alive active — icon-only button, 3:1 UI minimum)
            "accent_orange":        "#c66d2e",
            "accent_orange_border": "#e0843a",
            "accent_orange_hover":  "#d47a34",

            # Status strip — success
            "status_success_bg":     "#2c3f2c",
            "status_success_text":   "#ccffcc",
            "status_success_border": "#56c856",

            # Status strip — warning
            "status_warning_bg":     "#3a2f1a",
            "status_warning_text":   "#ffcc99",
            "status_warning_border": "#ffaa00",

            # Status strip — idle
            "status_idle_bg":     "#2f2f36",
            "status_idle_text":   "#c8c8d0",
            "status_idle_border": "#55555c",

            # Buttons
            "btn_bg":       "#35353c",
            "btn_border":   "#45454c",
            "btn_hover":    "#3e3e45",
            "btn_disabled": "#2a2a30",
            "btn_text":     "#e8e8ed",

            # Dropdowns
            "dropdown_bg":          "#2f2f36",
            "dropdown_text":        "#e8e8ed",
            "dropdown_border":      "#3a3a42",
            "dropdown_list_bg":     "#1e1e23",
            "dropdown_sel_bg":      "#3a3a42",
            "dropdown_sel_text":    "#ffffff",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#3a3a42",
            "toon_btn_inactive_border": "#4a4a52",
            "toon_btn_inactive_hover":  "#444450",
            "toon_btn_inactive_hover_border": "#5a5a62",

            # Slot accent colors (badge circles)
            "slot_1": "#5b9bf5",
            "slot_2": "#4ade80",
            "slot_3": "#f59e42",
            "slot_4": "#b07cf5",
            "slot_dim": "#2f2f36",

            # Toon cards (floating on gradient)
            "card_toon_bg":        "#2a2a30",
            "card_toon_border":    "#35353c",
            "card_toon_active_bg": "#1f2e22",

            # Segment status bar
            "segment_off":    "#1e1e23",
            "segment_found":  "#35353c",
            "segment_active": "#3aaa5e",

            # Full UI tokens
            # status_dot_active/segment_active are decorative (no text on them) —
            # kept saturated for visual punch. Game pills are text-bearing and pair
            # with text_on_accent above; violet-400 / 6.2:1, blue-400 / 6.7:1.
            "status_dot_active": "#3aaa5e",
            "status_dot_idle":   "#45454c",
            "game_pill_ttr":     "#a78bfa",
            "game_pill_cc":      "#60a5fa",
        }
    else:
        return {
            # Backgrounds  (elevation: sidebar < app < card < card_inner)
            "bg_app":        "#f8fafc",
            "bg_card":       "#ffffff",
            "bg_card_inner": "#f1f5f9",
            "bg_input":      "#ffffff",
            "bg_input_dark": "#e8ecf1",
            "bg_status":     "#f8fafc",

            # Sidebar
            "sidebar_bg":       "#e8ecf1",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(15,23,42,0.07)",
            "sidebar_text":     "#475569",
            "sidebar_text_sel": "#0f172a",
            "sidebar_border":   "#cbd5e1",

            # Header
            "header_bg":     "#f8fafc",
            "header_text":   "#0f172a",
            "header_accent": "#2563eb",

            # Borders
            "border_card":  "#e2e8f0",
            "border_input": "#cbd5e1",
            "border_muted": "#e8ecf1",
            "border_light": "#cbd5e1",

            # Text
            "text_primary":   "#0f172a",
            "text_secondary": "#334155",
            "text_muted":     "#475569",
            "text_disabled":  "#64748b",

            # On-accent text/icon — universal pair for every text-bearing accent
            # surface in the light palette (white on green-700/blue-600/orange-700/
            # red-700/violet-600 all clear AA).
            "text_on_accent": "#ffffff",

            # Accent — green (text-bearing surface, e.g. Enable button)
            # green-700 / 5.0:1 vs white (AA). green-600 #16a34a is reserved for
            # decorative roles (status dot, segment) where 3:1 UI minimum applies.
            "accent_green":        "#15803d",
            "accent_green_border": "#22c55e",
            "accent_green_hover":  "#166534",
            "accent_green_hover_border": "#15803d",
            "accent_green_subtle": "#86efac",

            # Accent — blue
            "accent_blue": "#5ba8c8",
            "accent_blue_btn":        "#2563eb",
            "accent_blue_btn_border": "#1d4ed8",
            "accent_blue_btn_hover":  "#1e40af",

            # Accent — red
            "accent_red":        "#b91c1c",
            "accent_red_border": "#dc2626",
            "accent_red_hover":  "#991b1b",
            "accent_red_hover_border": "#b91c1c",

            # Accent — orange (keep-alive active)
            "accent_orange":        "#c2410c",
            "accent_orange_border": "#ea580c",
            "accent_orange_hover":  "#9a3412",

            # Status strip — success
            "status_success_bg":     "#dcfce7",
            "status_success_text":   "#166534",
            "status_success_border": "#16a34a",

            # Status strip — warning
            "status_warning_bg":     "#fef3c7",
            "status_warning_text":   "#92400e",
            "status_warning_border": "#f59e0b",

            # Status strip — idle
            "status_idle_bg":     "#f1f5f9",
            "status_idle_text":   "#334155",
            "status_idle_border": "#cbd5e1",

            # Buttons
            "btn_bg":       "#e8ecf1",
            "btn_border":   "#cbd5e1",
            "btn_hover":    "#dbe2ea",
            "btn_disabled": "#f1f5f9",
            "btn_text":     "#0f172a",

            # Dropdowns
            "dropdown_bg":          "#ffffff",
            "dropdown_text":        "#0f172a",
            "dropdown_border":      "#cbd5e1",
            "dropdown_list_bg":     "#f8fafc",
            "dropdown_sel_bg":      "#e2e8f0",
            "dropdown_sel_text":    "#0f172a",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#e8ecf1",
            "toon_btn_inactive_border": "#cbd5e1",
            "toon_btn_inactive_hover":  "#dbe2ea",
            "toon_btn_inactive_hover_border": "#94a3b8",

            # Slot accent colors (badge circles — text-bearing, paired with white digit)
            # All four cleared AA against white: blue-600 5.7, green-700 5.0,
            # orange-700 5.0, violet-600 5.4.
            "slot_1": "#2563eb",
            "slot_2": "#15803d",
            "slot_3": "#c2410c",
            "slot_4": "#7c3aed",
            "slot_dim": "#cbd5e1",

            # Toon cards
            "card_toon_bg":        "#ffffff",
            "card_toon_border":    "#e2e8f0",
            "card_toon_active_bg": "#f0fdf4",

            # Segment status bar
            "segment_off":    "#e2e8f0",
            "segment_found":  "#cbd5e1",
            "segment_active": "#16a34a",

            # Full UI tokens
            "status_dot_active": "#16a34a",
            "status_dot_idle":   "#cbd5e1",
            "game_pill_ttr":     "#7c3aed",
            "game_pill_cc":      "#2563eb",
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
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #f6f6f6, stop:1 #ebebeb);
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