from PySide6.QtGui import QPalette, QFont, QPixmap, QPainter, QColor, QIcon, QPen, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget, QLabel
from PySide6.QtCore import Qt, QRectF, QObject, Signal, Slot
import math
import os
import sys
import time

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
        # Slate-900 at low alpha — less muddy than pure black on a cool-slate base
        shadow.setColor(QColor(15, 23, 42, 32))
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

            # Text/icon paired with accent surfaces. White on saturated accents
            # is what the v2.0.3 dark theme used; matches the Compact button look.
            "text_on_accent": "#ffffff",

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

            # Full UI tokens (no v2.0.3 equivalent; chosen for dark mode visual
            # consistency and AA contrast with text_on_accent = white).
            "status_dot_active": "#56c856",   # matches segment_active green
            "status_dot_idle":   "#555555",   # matches border_light
            "game_pill_ttr":     "#7e57c2",   # deeper violet, ~4.6:1 with white (AA)
            "game_pill_cc":      "#0077ff",   # matches accent_blue_btn for consistency
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
            stop:0 #f8fafc, stop:1 #eef2f7);
        color: #0f172a;
    }
    QPushButton {
        background-color: #e8ecf1;
        color: #0f172a;
        border-radius: 8px;
        padding: 6px 14px;
        border: 1px solid #cbd5e1;
    }
    QPushButton:hover {
        background-color: #dbe2ea;
        border: 1px solid #94a3b8;
    }
    QPushButton:pressed {
        background-color: #cbd5e1;
        border: 1px solid #94a3b8;
        padding-top: 7px;
        padding-bottom: 5px;
    }
    QPushButton:disabled {
        background-color: #f1f5f9;
        color: #94a3b8;
        border: 1px solid #e2e8f0;
    }
    QComboBox {
        background-color: #ffffff;
        color: #0f172a;
        border-radius: 8px;
        padding: 4px 8px;
        border: 1px solid #cbd5e1;
    }
    QComboBox QAbstractItemView {
        background-color: #f8fafc;
        selection-background-color: #e2e8f0;
        color: #0f172a;
    }
"""


# GNOME-like desktops where the xdg-desktop-portal Qt plugin's behavior
# (portal file dialogs, portal-driven appearance settings, etc.) is
# expected by users. On other desktops we fall back to a direct portal
# query in _color_scheme_from_portal so we still detect dark-mode without
# changing Qt's own behavior.
#
# Cinnamon is intentionally NOT in this list: it uses
# org.cinnamon.desktop.interface.gtk-theme, not the freedesktop appearance
# portal, so loading the Qt portal plugin there wouldn't give live updates
# anyway. Cinnamon users who want portal integration can set
# QT_QPA_PLATFORMTHEME=xdgdesktopportal explicitly in their environment.
_GNOME_LIKE_DESKTOPS = ("gnome", "unity", "pantheon", "budgie")


def should_set_xdg_portal_platformtheme(plugin_path: str) -> bool:
    """Return True if main.py should set QT_QPA_PLATFORMTHEME=xdgdesktopportal.

    Conditions:
      1. QT_QPA_PLATFORMTHEME is not already set (don't override KDE's "kde",
         user customizations, etc.). Empty string ("") is treated as not-set
         by the truthy check.
      2. The xdg-desktop-portal Qt platform theme plugin file exists at
         the given path.
      3. XDG_CURRENT_DESKTOP contains a token from _GNOME_LIKE_DESKTOPS
         (case-insensitive substring match, so "ubuntu:GNOME", "GNOME-Classic",
         and "Budgie:GNOME" all match). Cinnamon ("X-Cinnamon") is intentionally
         excluded — see the comment above _GNOME_LIKE_DESKTOPS for the rationale.

    Pure function for testability — main.py supplies plugin_path, and the
    caller decides what to do with the result.
    """
    if os.environ.get("QT_QPA_PLATFORMTHEME"):
        return False
    if not os.path.exists(plugin_path):
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return any(token in desktop for token in _GNOME_LIKE_DESKTOPS)


def _color_scheme_from_qt() -> str | None:
    """Ask Qt for the OS color-scheme preference.

    Reliable on Windows and macOS natively. On Linux it depends on Qt loading
    a platform theme plugin (xdgdesktopportal / qgnomeplatform / kde) that
    bridges to the desktop's appearance settings; main.py sets
    QT_QPA_PLATFORMTHEME=xdgdesktopportal when available so this works on
    GNOME without extra dependencies. Returns None when Qt has no opinion.
    """
    app = QApplication.instance()
    if app is None:
        return None
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    return None


def _color_scheme_from_portal(timeout: float = 1.0) -> str | None:
    """Linux fallback: query xdg-desktop-portal directly via D-Bus.

    Used when Qt can't answer (e.g. the xdgdesktopportal Qt plugin is not
    installed but the portal itself is running). Returns None on any failure.

    Per the org.freedesktop.appearance spec:
      0 = no preference, 1 = prefer dark, 2 = prefer light.
    """
    if sys.platform != "linux":
        return None
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except Exception:
        return None
    addr = DBusAddress(
        "/org/freedesktop/portal/desktop",
        bus_name="org.freedesktop.portal.Desktop",
        interface="org.freedesktop.portal.Settings",
    )
    try:
        with open_dbus_connection(bus="SESSION") as conn:
            msg = new_method_call(
                addr, "Read", "ss", ("org.freedesktop.appearance", "color-scheme")
            )
            reply = conn.send_and_get_reply(msg, timeout=timeout)
    except Exception:
        return None
    body = reply.body
    if not body:
        return None
    # Settings.Read returns Variant<Variant<uint32>>. jeepney encodes a
    # variant as a (signature_str, value) tuple, so we unwrap any nested
    # variant tuples — but a generic "take body[0] until non-tuple" walk
    # would land on the signature string ('v'/'u') instead of the value.
    value = body[0]
    while isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        value = value[1]
    if value == 1:
        return "dark"
    if value == 2:
        return "light"
    return None


# Cache for detect_system_color_scheme. Invalidated explicitly by
# SystemThemeWatcher when QStyleHints reports a change, and aged out
# by a short TTL so a missed signal can't pin the cache to a stale
# value forever. The cache is critical because resolve_theme() is
# invoked from every tab's refresh_theme / paint cascade — without
# memoisation each call hits _color_scheme_from_portal on stacks
# without a Qt platform theme plugin (1 s blocking D-Bus per paint).
_SYSTEM_COLOR_SCHEME_CACHE: tuple[str, float] | None = None
_SYSTEM_COLOR_SCHEME_CACHE_TTL: float = 1.0


def invalidate_system_color_scheme_cache() -> None:
    """Drop the cached system color-scheme.

    Call this whenever an external signal indicates the OS color scheme may
    have changed, so the next detect_system_color_scheme() call re-queries
    the OS. SystemThemeWatcher does this automatically for Qt-delivered
    notifications; other callers (e.g. an application-level settings change
    handler) can call it directly.
    """
    global _SYSTEM_COLOR_SCHEME_CACHE
    _SYSTEM_COLOR_SCHEME_CACHE = None


def detect_system_color_scheme() -> str:
    """Return 'dark' or 'light' for the OS color-scheme preference.

    Order: Qt styleHints, then xdg-desktop-portal direct (Linux only), then
    QPalette inspection as a last-resort heuristic.

    Result is memoised for _SYSTEM_COLOR_SCHEME_CACHE_TTL seconds; the cache
    is invalidated explicitly by SystemThemeWatcher and ages out on the TTL.
    """
    global _SYSTEM_COLOR_SCHEME_CACHE
    cached = _SYSTEM_COLOR_SCHEME_CACHE
    if cached is not None and time.monotonic() - cached[1] < _SYSTEM_COLOR_SCHEME_CACHE_TTL:
        return cached[0]
    answer = _color_scheme_from_qt()
    if answer is None:
        answer = _color_scheme_from_portal()
    if answer is None:
        app = QApplication.instance()
        if app is not None:
            answer = "dark" if app.palette().color(QPalette.Base).value() < 128 else "light"
        else:
            answer = "light"
    _SYSTEM_COLOR_SCHEME_CACHE = (answer, time.monotonic())
    return answer


def resolve_theme(settings_manager) -> str:
    user_pref = settings_manager.get("theme", "system")
    if user_pref in ("light", "dark"):
        return user_pref
    return detect_system_color_scheme()


class SystemThemeWatcher(QObject):
    """Emits when the OS-level color-scheme preference changes.

    Hooks QStyleHints.colorSchemeChanged, which fires natively on Windows and
    macOS, and on Linux when a platform theme plugin (xdgdesktopportal etc.)
    is active. Consumers connect to system_theme_changed and re-apply their
    theme only when the user's preference is set to "system".

    De-duplicates repeated emits of the same value so consumers don't
    re-render on no-op signals.
    """

    system_theme_changed = Signal(str)  # 'dark' or 'light'

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._last_emitted: str | None = None
        app = QApplication.instance()
        if app is not None:
            app.styleHints().colorSchemeChanged.connect(self._on_qt_changed)

    @Slot(Qt.ColorScheme)
    def _on_qt_changed(self, _scheme: Qt.ColorScheme):
        # Drop any cached value first so detect_system_color_scheme actually
        # re-queries the OS — otherwise we'd echo whatever was cached at the
        # last paint and miss the change we were notified about.
        invalidate_system_color_scheme_cache()
        value = detect_system_color_scheme()
        if value == self._last_emitted:
            return
        self._last_emitted = value
        self.system_theme_changed.emit(value)


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


def _fusion_dark_palette() -> QPalette:
    """Hand-built Fusion-style dark palette.

    Used by apply_theme() to override the default light palette so Qt's
    Wayland CSD titlebar (and any other native chrome that draws from
    QPalette rather than the stylesheet) renders dark. Avoids
    QStyleHints.setColorScheme() because that takes ownership of the
    color-scheme property away from the OS-tracking layer, which would
    suppress colorSchemeChanged signals on subsequent OS toggles and
    break live-update.
    """
    p = QPalette()
    p.setColor(QPalette.Window, QColor(53, 53, 53))
    p.setColor(QPalette.WindowText, Qt.white)
    p.setColor(QPalette.Base, QColor(35, 35, 35))
    p.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    p.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    p.setColor(QPalette.ToolTipText, Qt.white)
    p.setColor(QPalette.Text, Qt.white)
    p.setColor(QPalette.Button, QColor(53, 53, 53))
    p.setColor(QPalette.ButtonText, Qt.white)
    p.setColor(QPalette.BrightText, Qt.red)
    p.setColor(QPalette.Link, QColor(42, 130, 218))
    p.setColor(QPalette.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, Qt.black)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(127, 127, 127))
    return p


def apply_theme(app, theme: str):
    global _APPLIED_THEME
    _APPLIED_THEME = theme if theme in ("dark", "light") else None
    if theme == "dark":
        app.setStyleSheet(DARK_THEME)
        # Set a dark QPalette so the Wayland CSD titlebar (which Qt draws
        # from QPalette, not from the stylesheet) renders dark to match
        # the in-window content. Without this, dark content has a jarring
        # light titlebar.
        app.setPalette(_fusion_dark_palette())
    elif theme == "light":
        app.setStyleSheet(LIGHT_THEME)
        # Reset to the platform-default (light) palette so the titlebar
        # tracks the rest of the desktop. style().standardPalette() is the
        # canonical "current style's default palette," not the stale value
        # we may have overridden during a prior dark-theme apply.
        app.setPalette(app.style().standardPalette())
    else:
        app.setStyleSheet("")
        app.setPalette(app.style().standardPalette())