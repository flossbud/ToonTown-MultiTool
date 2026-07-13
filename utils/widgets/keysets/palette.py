"""Theme-aware colors for the keysets page (2026-07-12 spec).

One pure function per surface. Dark branches return the literals the widgets
hardcoded before this module existed, byte-for-byte, so dark theme cannot
change. Light branches implement the approved Vivid design: identity-tinted
cards (lighten of the set color, mirroring the existing darken family) with
frosted white-alpha surfaces and dark ink.

Deliberate non-token light literals (single definition sites, see spec):
#33415f ink on pastel tints; #1e293b is owned by PillButton (not here);
#94a3b8 add-set dashes; the #e05252 red family carries error semantics in
both themes. Token-valued literals carry token-name comments and are pinned
by tests/test_keysets_palette.py.

Leaf module: QColor + utils.color_math only.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

from utils.color_math import darken_rgb, lighten_rgb, with_alpha

# Vivid mix fractions - same constants as utils/card_palette.py.
VIVID_TOP_F, VIVID_BOT_F = 0.58, 0.72


def detail_card(c: str, b: str, is_dark: bool):
    """Editor card (top, bot, border). Dark: legacy darken family, alpha
    border. Light: Vivid identity tint, solid border."""
    if is_dark:
        return (darken_rgb(QColor(c), 0.30), darken_rgb(QColor(c), 0.15),
                with_alpha(b, 0.55))
    return (lighten_rgb(QColor(c), VIVID_TOP_F), lighten_rgb(QColor(c), VIVID_BOT_F),
            QColor(b))


def rail_item(c: str, b: str, selected: bool, is_dark: bool):
    """SetListItem body (top, bot, border). Selected is accent-bright and
    identical in both themes; unselected mirrors the card family."""
    if selected:
        return (darken_rgb(QColor(c), 0.95), darken_rgb(QColor(c), 0.72), QColor(b))
    if is_dark:
        return (darken_rgb(QColor(c), 0.30), darken_rgb(QColor(c), 0.15),
                with_alpha(b, 0.55))
    return (lighten_rgb(QColor(c), VIVID_TOP_F), lighten_rgb(QColor(c), VIVID_BOT_F),
            with_alpha(b, 0.55))


def keycap(state: str, accent_b: str, hover: bool, is_dark: bool):
    """Visual-keyboard cap (fill, border, ink) per state."""
    if state == "conflict":
        return QColor("#e05252"), QColor("#f28b8b"), QColor("#ffffff")
    if state == "movement":
        if is_dark:
            return QColor(accent_b), with_alpha("#ffffff", 0.55), QColor("#ffffff")
        return QColor(accent_b), with_alpha("#ffffff", 0.7), QColor("#ffffff")
    if state == "aux":
        if is_dark:
            return (with_alpha("#ffffff", 0.22), with_alpha("#ffffff", 0.40),
                    QColor("#ffffff"))
        return QColor("#ffffff"), QColor("#475569"), QColor("#0f172a")  # text_muted border
    # unassigned
    if is_dark:
        fill_a = 0.18 if hover else 0.28
        return (with_alpha("#000000", fill_a), with_alpha("#ffffff", 0.08),
                with_alpha("#ffffff", 0.40))
    fill_a = 0.70 if hover else 0.55
    return (with_alpha("#ffffff", fill_a), with_alpha("#0f172a", 0.14),
            QColor("#334155"))


def spotlight_ring(is_dark: bool) -> QColor:
    return with_alpha("#ffffff", 0.9) if is_dark else with_alpha("#0f172a", 0.9)


def card_ink(is_dark: bool) -> str:
    return "#ffffff" if is_dark else "#0f172a"          # text_primary


def card_ink_soft(is_dark: bool) -> str:
    return "rgba(255,255,255,0.62)" if is_dark else "#33415f"


def card_ink_faint(is_dark: bool) -> str:
    return "rgba(255,255,255,0.5)" if is_dark else "#33415f"


def pencil_css(is_dark: bool) -> str:
    if is_dark:
        return ("QPushButton { background: transparent; border: none; "
                "color: rgba(255,255,255,0.55); font-size: 13px; }"
                "QPushButton:hover { color: #ffffff; }")
    return ("QPushButton { background: transparent; border: none; "
            "color: rgba(15,23,42,0.5); font-size: 13px; }"
            "QPushButton:hover { color: #0f172a; }")


def field_row(active: bool, accent_b: str, is_dark: bool):
    """FieldRow (bg_css, border_css). Active accent tint is theme-independent."""
    if active:
        return (with_alpha(accent_b, 0.12).name(QColor.HexArgb),
                with_alpha(accent_b, 0.5).name(QColor.HexArgb))
    if is_dark:
        return "rgba(0,0,0,0.24)", "rgba(0,0,0,0.30)"
    return "rgba(255,255,255,0.45)", "rgba(15,23,42,0.14)"


def field_value(conflict: bool, is_dark: bool):
    """Key value pill (bg, border, ink) css strings."""
    if conflict:
        if is_dark:
            return "rgba(224,82,82,0.16)", "#e05252", "#ff9a9a"
        return "rgba(224,82,82,0.10)", "#e05252", "#b91c1c"
    if is_dark:
        return "rgba(0,0,0,0.35)", "rgba(255,255,255,0.14)", "#ffffff"
    return "#ffffff", "rgba(15,23,42,0.18)", "#0f172a"


def conflict_banner_css(is_dark: bool, radius: int) -> str:
    if is_dark:
        return ("background: rgba(224,82,82,0.14); border: 1px solid #e05252; "
                "border-radius: %dpx; color: #ff9a9a; font-size: 11.5px; "
                "padding: 8px 12px;" % radius)
    return ("background: rgba(224,82,82,0.10); border: 1px solid #e05252; "
            "border-radius: %dpx; color: #b91c1c; font-size: 11.5px; "
            "padding: 8px 12px;" % radius)


def rail_panel_qss(is_dark: bool) -> str:
    if is_dark:
        return ("SetListPanel { background-color: rgba(0,0,0,0.24); "
                "border: 1px solid rgba(0,0,0,0.30); border-radius: 20px; }")
    return ("SetListPanel { background-color: #e8ecf1; "        # bg_input_dark
            "border: 1px solid #cbd5e1; border-radius: 20px; }")  # border_light


def rail_header_ink(is_dark: bool) -> str:
    return "rgba(255,255,255,0.5)" if is_dark else "#475569"    # text_muted


def rail_item_ink(selected: bool, is_dark: bool) -> str:
    """Name-label ink. White on the accent-filled selected body (both themes)
    and on dark unselected bodies; dark ink on light pastel bodies."""
    if selected or is_dark:
        return "#ffffff"
    return "#0f172a"                                            # text_primary


def rail_chip_qss(selected: bool, is_dark: bool) -> str:
    """_Keycap preview chip. Frosted-dark on dark or accent bodies; frosted-
    light with dark ink on light pastel bodies."""
    base = ("border-radius: 5px; font-weight: 700; font-size: 9px; "
            "font-family: 'Consolas', 'Menlo', 'DejaVu Sans Mono', "
            "'Liberation Mono', monospace; padding: 0 4px;")
    if selected or is_dark:
        return ("background-color: rgba(0,0,0,0.28); "
                "border: 1px solid rgba(255,255,255,0.14); "
                "color: rgba(255,255,255,0.9); " + base)
    return ("background-color: rgba(255,255,255,0.55); "
            "border: 1px solid rgba(15,23,42,0.14); "
            "color: #334155; " + base)


def add_set_qss(is_dark: bool) -> str:
    """Dashed capsule. NO margin property - the old QSS margin-top was carved
    out of the fixed-height box and squished the capsule (root cause,
    2026-07-12); the gap now lives in the widget's fixed height."""
    if is_dark:
        return ("QPushButton { background: transparent; color: #aaaaaa; "
                "border: 1.5px dashed rgba(255,255,255,0.22); border-radius: 12px; "
                "font-size: 12.5px; font-weight: 600; }"
                "QPushButton:hover { background: rgba(255,255,255,0.07); }")
    return ("QPushButton { background: transparent; color: #64748b; "        # text_disabled
            "border: 1.5px dashed #94a3b8; border-radius: 12px; "
            "font-size: 12.5px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(15,23,42,0.05); }")


def picker_card_fill(is_dark: bool) -> QColor:
    return QColor("#0d0f13") if is_dark else QColor("#ffffff")


def picker_ink(kind: str, is_dark: bool) -> str:
    if is_dark:
        return {"title": "#ffffff", "soft": "rgba(255,255,255,0.6)",
                "meta": "rgba(255,255,255,0.7)", "subtitle": "rgba(255,255,255,0.55)"}[kind]
    return {"title": "#0f172a", "soft": "#33415f",
            "meta": "#33415f", "subtitle": "#33415f"}[kind]


def back_button_qss(is_dark: bool) -> str:
    if is_dark:
        return ("QPushButton {"
                " background: transparent; border: none;"
                " color: rgba(255,255,255,0.66);"
                " padding: 4px 10px 4px 4px;"
                " font-size: 13.5px; font-weight: 600; text-align: left;"
                "}"
                "QPushButton:hover { color: #ffffff; }")
    return ("QPushButton {"
            " background: transparent; border: none;"
            " color: rgba(15,23,42,0.66);"
            " padding: 4px 10px 4px 4px;"
            " font-size: 13.5px; font-weight: 600; text-align: left;"
            "}"
            "QPushButton:hover { color: #0f172a; }")
