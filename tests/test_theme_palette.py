"""Tests for the dark/light color tokens returned by get_theme_colors()."""

from utils.theme_manager import get_theme_colors


def test_dark_palette_uses_charcoal_app_bg():
    c = get_theme_colors(is_dark=True)
    assert c["bg_app"] == "#1a1a1f"
    assert c["bg_card"] == "#2a2a30"
    assert c["bg_card_inner"] == "#2f2f36"
    assert c["sidebar_bg"] == "#131316"


def test_dark_palette_text_is_softer_than_pure_white():
    c = get_theme_colors(is_dark=True)
    assert c["text_primary"] == "#e8e8ed"
    assert c["text_secondary"] == "#c8c8d0"


def test_dark_palette_accent_green_is_saturated():
    c = get_theme_colors(is_dark=True)
    assert c["accent_green"] == "#3aaa5e"


def test_dark_palette_accent_blue_btn_is_less_neon():
    c = get_theme_colors(is_dark=True)
    assert c["accent_blue_btn"] == "#3a6dd8"


def test_dark_palette_includes_full_ui_tokens():
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_active"] == "#3aaa5e"
    assert c["status_dot_idle"] == "#45454c"
    assert c["game_pill_ttr"] == "#7e57c2"
    assert c["game_pill_cc"] == "#3a6dd8"
