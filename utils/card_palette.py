"""Theme-aware Multitoon pinwheel card palette (Unified design, 2026-07-12).

One frozen value object holds every LIT and OFF endpoint color a card
paints. The single style-writer (CompactQuadrantLayout.set_card_brand)
builds it per card from the live theme tokens and injects it into the
paint widgets; widgets lerp lit -> off by dim progress and never query
the theme.

Dark fields reproduce the original hardcoded pinwheel formulas exactly
(dark theme byte-identical by construction). Light fields implement the
Unified design: Vivid lit (2026-07-09 spec) + Paper off (2026-07-12 spec).

Leaf module: QColor + utils.card_dim + utils.color_math only.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

from utils.card_dim import dim_color, lerp_color
from utils.color_math import darken_rgb, lighten_rgb

# Portrait-pixmap dim parameters (fed to card_dim.dim_pixmap).
DARK_PIXMAP_SAT, DARK_PIXMAP_BRIGHT = 0.45, 0.75    # == card_dim.SAT/BRIGHT
LIGHT_PIXMAP_SAT, LIGHT_PIXMAP_BRIGHT = 0.35, 1.0   # desaturate, never darken

# Vivid lit mix fractions (2026-07-09 spec; mirror of dark's 0.28/0.14 family).
VIVID_TOP_F, VIVID_BOT_F = 0.58, 0.72
VIVID_BADGE_F = 0.50
VIVID_TRACK_F = 0.48


@dataclass(frozen=True)
class CardPalette:
    is_dark: bool
    # Body gradient endpoints (5px-border card fill).
    body_top_lit: QColor
    body_bot_lit: QColor
    body_top_off: QColor
    body_bot_off: QColor
    # Inner border + portrait ring.
    border_lit: QColor
    border_off: QColor
    # Name/stat ink: rgb and alpha carried separately so the dark
    # stylesheet strings stay byte-identical (0.620 / 0.500).
    name_rgb_lit: QColor
    name_a_lit: float
    name_rgb_off: QColor
    name_a_off: float
    stat_rgb_lit: QColor
    stat_a_lit: float
    stat_rgb_off: QColor
    stat_a_off: float
    # Slot badge fallback circle. Off pair None = badge keeps its legacy
    # dim-pixmap-only path (dark theme).
    badge_bg_lit: QColor
    badge_ink_lit: QColor
    badge_bg_off: "QColor | None"
    badge_ink_off: "QColor | None"
    # Keyset selector off endpoints. None = legacy dim_color() lerp.
    keyset_off_bg: "QColor | None"
    keyset_off_text: "QColor | None"
    keyset_off_border: "QColor | None"
    keyset_off_label: "QColor | None"
    # Keep-alive capsule glass (CSS rgba fragments) + progress track.
    ka_glass_bg: str
    ka_glass_border: str
    track_lit: QColor
    track_off: QColor
    # Status-dot cutout ring (lit only; the dot hides when off).
    status_cutout: QColor
    # Recessed-chip QSS colors (power / click-sync off states).
    chip_off_bg: str
    chip_off_border: str
    chip_off_hover: str
    chip_off_disabled: str
    # FeaturePill ink family (True = dark-on-light).
    pill_light_chrome: bool
    # Portrait-pixmap dim parameters.
    pixmap_sat: float
    pixmap_bright: float


def card_palette(
    accent: QColor, body_override: "QColor | None", c: dict, is_dark: bool
) -> CardPalette:
    """Build the palette for one card. `accent` = custom accent, else game
    brand, else border_light (empty). `body_override` = custom body pick."""
    accent = QColor(accent)
    base = QColor(body_override) if body_override is not None else QColor(accent)
    if is_dark:
        dim_base = dim_color(base)
        return CardPalette(
            is_dark=True,
            body_top_lit=darken_rgb(base, 0.28),
            body_bot_lit=darken_rgb(base, 0.14),
            body_top_off=darken_rgb(dim_base, 0.28),
            body_bot_off=darken_rgb(dim_base, 0.14),
            border_lit=QColor(accent),
            border_off=dim_color(accent),
            name_rgb_lit=QColor("#ffffff"), name_a_lit=1.0,
            name_rgb_off=QColor("#ffffff"), name_a_off=0.62,
            stat_rgb_lit=QColor("#ffffff"), stat_a_lit=0.9,
            stat_rgb_off=QColor("#ffffff"), stat_a_off=0.5,
            badge_bg_lit=QColor("#101010"),
            badge_ink_lit=QColor("#ffffff"),
            badge_bg_off=None,
            badge_ink_off=None,
            keyset_off_bg=None,
            keyset_off_text=None,
            keyset_off_border=None,
            keyset_off_label=None,
            ka_glass_bg="rgba(0,0,0,0.24)",
            ka_glass_border="rgba(0,0,0,0.30)",
            track_lit=QColor("#0d0d0d"),
            track_off=QColor("#0d0d0d"),
            status_cutout=darken_rgb(accent, 0.21),
            chip_off_bg="rgba(0,0,0,0.24)",
            chip_off_border="rgba(0,0,0,0.30)",
            chip_off_hover="rgba(255,255,255,0.10)",
            chip_off_disabled="rgba(0,0,0,0.30)",
            pill_light_chrome=False,
            pixmap_sat=DARK_PIXMAP_SAT,
            pixmap_bright=DARK_PIXMAP_BRIGHT,
        )
    top_lit = lighten_rgb(base, VIVID_TOP_F)
    empty = accent == QColor(c["border_light"])
    return CardPalette(
        is_dark=False,
        body_top_lit=top_lit,
        body_bot_lit=lighten_rgb(base, VIVID_BOT_F),
        body_top_off=QColor(c["bg_card_inner"]),
        body_bot_off=QColor(c["bg_card_inner_hover"]),
        border_lit=QColor(accent),
        # Paper: an assigned toon keeps a desaturated steel ring of its
        # accent; an empty slot reads as pure paper (the token itself).
        border_off=QColor(c["border_light"]) if empty else dim_color(accent),
        name_rgb_lit=QColor(c["text_primary"]), name_a_lit=1.0,
        name_rgb_off=QColor(c["text_muted"]), name_a_off=1.0,
        stat_rgb_lit=QColor(c["text_secondary"]), stat_a_lit=0.9,
        stat_rgb_off=QColor(c["text_disabled"]), stat_a_off=1.0,
        badge_bg_lit=lighten_rgb(base, VIVID_BADGE_F),
        badge_ink_lit=QColor(c["text_muted"]),
        badge_bg_off=QColor(c["bg_input_dark"]),
        badge_ink_off=lerp_color(
            QColor(c["border_input"]), QColor(c["text_disabled"]), 0.5
        ),
        keyset_off_bg=QColor(c["bg_input_dark"]),
        keyset_off_text=QColor(c["text_muted"]),
        keyset_off_border=QColor(c["border_light"]),
        keyset_off_label=QColor(c["text_muted"]),
        ka_glass_bg="rgba(0,0,0,0.06)",
        ka_glass_border="rgba(0,0,0,0.13)",
        track_lit=lighten_rgb(base, VIVID_TRACK_F),
        track_off=QColor(c["bg_input_dark"]),
        status_cutout=QColor(top_lit),
        chip_off_bg=c["bg_card_inner_hover"],          # #e2e8f0 solid
        chip_off_border=c["border_light"],             # #cbd5e1
        chip_off_hover="#d8dee7",
        chip_off_disabled=c["bg_input_dark"],           # #e8ecf1
        pill_light_chrome=True,
        pixmap_sat=LIGHT_PIXMAP_SAT,
        pixmap_bright=LIGHT_PIXMAP_BRIGHT,
    )
