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


def test_dark_palette_accent_green_pairs_with_dark_text():
    """Material 3 onPrimary pattern: bright surface + dark text clears AAA in dark mode."""
    c = get_theme_colors(is_dark=True)
    assert c["accent_green"] == "#4ade80"  # green-400, ~9.7:1 vs text_on_accent
    assert c["text_on_accent"] == "#0f172a"


def test_dark_palette_accent_blue_btn_pairs_with_dark_text():
    c = get_theme_colors(is_dark=True)
    assert c["accent_blue_btn"] == "#60a5fa"  # blue-400, ~6.7:1 vs text_on_accent


def test_dark_palette_accent_red_pairs_with_dark_text():
    c = get_theme_colors(is_dark=True)
    assert c["accent_red"] == "#f87171"  # red-400, ~6.3:1 vs text_on_accent


def test_dark_palette_decorative_greens_remain_saturated():
    """status_dot_active/segment_active are no-text decorations — keep #3aaa5e."""
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_active"] == "#3aaa5e"
    assert c["segment_active"] == "#3aaa5e"


def test_dark_palette_includes_full_ui_tokens():
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_idle"] == "#45454c"
    assert c["game_pill_ttr"] == "#a78bfa"  # violet-400, paired with text_on_accent
    assert c["game_pill_cc"] == "#60a5fa"   # matches accent_blue_btn


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
    """Material 3 onPrimary pattern: every theme defines the token used as text/icon
    on top of every bright accent surface."""
    assert get_theme_colors(is_dark=True)["text_on_accent"] == "#0f172a"
    assert get_theme_colors(is_dark=False)["text_on_accent"] == "#ffffff"


def test_both_palettes_have_identical_keys():
    """Token coverage must match across themes — a missing key in one is a bug."""
    dark_keys = set(get_theme_colors(is_dark=True).keys())
    light_keys = set(get_theme_colors(is_dark=False).keys())
    assert dark_keys == light_keys, (
        f"dark only: {dark_keys - light_keys}, light only: {light_keys - dark_keys}"
    )
