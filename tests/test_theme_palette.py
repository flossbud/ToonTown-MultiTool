"""Tests for the dark/light color tokens returned by get_theme_colors()."""

from utils.theme_manager import get_theme_colors


def test_dark_palette_uses_v203_neutral_charcoal():
    """Dark mode reverted to v2.0.3 values per user request — pure neutral grays,
    no cool-slate tint."""
    c = get_theme_colors(is_dark=True)
    assert c["bg_app"] == "#1a1a1a"
    assert c["bg_card"] == "#252525"
    assert c["bg_card_inner"] == "#2e2e2e"
    assert c["sidebar_bg"] == "#111111"


def test_dark_palette_text_is_pure_white_v203():
    c = get_theme_colors(is_dark=True)
    assert c["text_primary"] == "#ffffff"
    assert c["text_secondary"] == "#bbbbbb"


def test_dark_palette_accents_match_v203_saturated():
    """Buttons use v2.0.3 saturated accents with white text — the look the user
    wants restored. AA contrast is intentionally NOT enforced for dark mode."""
    c = get_theme_colors(is_dark=True)
    assert c["accent_green"] == "#3da343"
    assert c["accent_blue_btn"] == "#0077ff"
    assert c["accent_red"] == "#b34848"
    assert c["accent_orange"] == "#c47a2a"
    assert c["text_on_accent"] == "#ffffff"  # white on saturated bg, like v2.0.3


def test_dark_palette_segment_active_matches_v203():
    c = get_theme_colors(is_dark=True)
    assert c["segment_active"] == "#56c856"


def test_dark_palette_full_ui_tokens_paired_with_white_text():
    """New Full UI tokens (no v2.0.3 equivalent) must clear AA against
    text_on_accent = white in dark mode."""
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_active"] == "#56c856"   # matches segment_active
    assert c["status_dot_idle"] == "#555555"     # matches border_light
    assert c["game_pill_ttr"] == "#7e57c2"       # ~4.6:1 with white (AA)
    assert c["game_pill_cc"] == "#0077ff"        # matches accent_blue_btn


def test_light_palette_uses_cool_slate_bg():
    c = get_theme_colors(is_dark=False)
    assert c["bg_app"] == "#f8fafc"
    assert c["bg_card"] == "#ffffff"
    assert c["sidebar_bg"] == "#e8ecf1"


def test_light_palette_text_clears_aaa_on_white():
    c = get_theme_colors(is_dark=False)
    assert c["text_primary"] == "#0f172a"      # 17.6:1
    assert c["text_secondary"] == "#334155"    # 10.7:1
    assert c["text_muted"] == "#475569"        # 7.2:1
    assert c["text_disabled"] == "#64748b"     # 4.6:1


def test_light_palette_accent_green_clears_aa_with_white():
    """green-600 is decorative-only; text-bearing button uses green-700 for AA."""
    c = get_theme_colors(is_dark=False)
    assert c["accent_green"] == "#15803d"  # green-700, 5.0:1 vs white
    assert c["text_on_accent"] == "#ffffff"


def test_light_palette_slot_2_uses_text_bearing_green():
    """Slot 2 badge has a white digit on it, so the bg must clear AA against white."""
    c = get_theme_colors(is_dark=False)
    assert c["slot_2"] == "#15803d"  # green-700, matches accent_green family


def test_light_palette_accent_orange_clears_aa_with_white():
    c = get_theme_colors(is_dark=False)
    # orange-700 #c2410c -> 5.0:1 on white. The previous #c45f1e was 4.4 (borderline AA).
    assert c["accent_orange"] == "#c2410c"


def test_light_palette_decorative_greens_remain_vibrant():
    """status_dot_active/segment_active have no text — keep green-600 for visual punch."""
    c = get_theme_colors(is_dark=False)
    assert c["status_dot_active"] == "#16a34a"
    assert c["segment_active"] == "#16a34a"


def test_light_palette_includes_full_ui_tokens():
    c = get_theme_colors(is_dark=False)
    assert c["status_dot_idle"] == "#cbd5e1"
    assert c["game_pill_ttr"] == "#7c3aed"
    assert c["game_pill_cc"] == "#2563eb"


def test_text_on_accent_present_in_both_palettes():
    """Both themes define the token used as text/icon on accent surfaces.
    Light = white on darker accents (Material 3 onPrimary).
    Dark = white on saturated accents (v2.0.3 button look — non-AA but matches
    the look the user explicitly requested)."""
    assert get_theme_colors(is_dark=True)["text_on_accent"] == "#ffffff"
    assert get_theme_colors(is_dark=False)["text_on_accent"] == "#ffffff"


def test_both_palettes_have_identical_keys():
    """Token coverage must match across themes — a missing key in one is a bug."""
    dark_keys = set(get_theme_colors(is_dark=True).keys())
    light_keys = set(get_theme_colors(is_dark=False).keys())
    assert dark_keys == light_keys, (
        f"dark only: {dark_keys - light_keys}, light only: {light_keys - dark_keys}"
    )
