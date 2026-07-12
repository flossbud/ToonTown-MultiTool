"""CardPalette: dark fields byte-equal legacy formulas; light fields = Unified design."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtGui import QColor

from utils.card_dim import dim_color, lerp_color
from utils.color_math import darken_rgb, lighten_rgb
from utils.theme_manager import get_theme_colors


TTR = QColor("#4A8FE7")
MOE = QColor("#e6d35a")          # pinned reference from the 2026-07-09 spec
EMPTY = None                     # empty slots pass accent=border_light, no body


def _pal(accent, body, is_dark):
    from utils.card_palette import card_palette
    c = get_theme_colors(is_dark)
    return card_palette(accent, body, c, is_dark)


def test_dark_body_and_border_match_legacy_formulas():
    p = _pal(TTR, None, True)
    dim_base = dim_color(TTR)
    assert p.body_top_lit == darken_rgb(TTR, 0.28)
    assert p.body_bot_lit == darken_rgb(TTR, 0.14)
    assert p.body_top_off == darken_rgb(dim_base, 0.28)
    assert p.body_bot_off == darken_rgb(dim_base, 0.14)
    assert p.border_lit == TTR
    assert p.border_off == dim_color(TTR)


def test_dark_ink_alphas_match_legacy_ramp():
    p = _pal(TTR, None, True)
    assert (p.name_rgb_lit, p.name_a_lit) == (QColor("#ffffff"), 1.0)
    assert (p.name_rgb_off, p.name_a_off) == (QColor("#ffffff"), 0.62)
    assert (p.stat_rgb_lit, p.stat_a_lit) == (QColor("#ffffff"), 0.9)
    assert (p.stat_rgb_off, p.stat_a_off) == (QColor("#ffffff"), 0.5)


def test_dark_chrome_matches_legacy_values():
    p = _pal(TTR, None, True)
    assert p.badge_bg_lit == QColor("#101010")
    assert p.badge_ink_lit == QColor("#ffffff")
    assert p.badge_bg_off is None and p.badge_ink_off is None
    assert p.keyset_off_bg is None            # legacy dim_color path
    assert p.ka_glass_bg == "rgba(0,0,0,0.24)"
    assert p.ka_glass_border == "rgba(0,0,0,0.30)"
    assert p.track_lit == QColor("#0d0d0d") and p.track_off == QColor("#0d0d0d")
    assert p.status_cutout == darken_rgb(TTR, 0.21)
    assert p.pill_light_chrome is False
    assert (p.pixmap_sat, p.pixmap_bright) == (0.45, 0.75)


def test_light_lit_is_vivid_with_pinned_moe_value():
    p = _pal(MOE, None, False)
    assert p.body_top_lit == lighten_rgb(MOE, 0.58)
    assert p.body_top_lit.name() == "#f4edba"          # spec-pinned
    assert p.body_bot_lit == lighten_rgb(MOE, 0.72)
    assert p.border_lit == MOE
    assert (p.name_rgb_lit.name(), p.name_a_lit) == ("#0f172a", 1.0)
    assert (p.stat_rgb_lit.name(), p.stat_a_lit) == ("#334155", 0.9)
    assert p.badge_bg_lit == lighten_rgb(MOE, 0.50)
    assert p.badge_ink_lit == QColor("#475569")
    assert p.status_cutout == p.body_top_lit


def test_light_off_is_paper_tokens():
    c = get_theme_colors(False)
    p = _pal(TTR, None, False)
    assert p.body_top_off == QColor(c["bg_card_inner"])
    assert p.body_bot_off == QColor(c["bg_card_inner_hover"])
    assert p.border_off == dim_color(TTR)              # assigned toon keeps steel ring
    assert (p.name_rgb_off.name(), p.name_a_off) == ("#475569", 1.0)
    assert (p.stat_rgb_off.name(), p.stat_a_off) == ("#64748b", 1.0)
    assert p.badge_bg_off == QColor(c["bg_input_dark"])
    assert p.badge_ink_off == lerp_color(QColor(c["border_input"]), QColor(c["text_disabled"]), 0.5)
    assert p.keyset_off_bg == QColor(c["bg_input_dark"])
    assert p.keyset_off_text == QColor(c["text_muted"])
    assert p.keyset_off_border == QColor(c["border_light"])
    assert p.keyset_off_label == QColor(c["text_muted"])
    assert p.ka_glass_bg == "rgba(0,0,0,0.06)"
    assert p.ka_glass_border == "rgba(0,0,0,0.13)"
    assert p.track_lit == QColor(c["bg_card"])
    assert p.track_off == QColor(c["bg_card"])
    assert p.pill_light_chrome is True
    assert (p.pixmap_sat, p.pixmap_bright) == (0.35, 1.0)


def test_light_empty_slot_border_is_token_not_dim():
    c = get_theme_colors(False)
    empty_accent = QColor(c["border_light"])
    p = _pal(empty_accent, None, False)
    # Empty slots read as pure paper: the off border is the token itself.
    assert p.border_off == QColor(c["border_light"])


def test_body_override_drives_fill_but_not_border():
    body = QColor("#1a1d29")
    p = _pal(TTR, body, False)
    assert p.body_top_lit == lighten_rgb(body, 0.58)   # "Literal" whitening
    assert p.border_lit == TTR
