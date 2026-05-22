"""Tests for the CC badge color helpers (background derivation)."""

from __future__ import annotations

from PySide6.QtGui import QColor

from utils import cc_badge_paint


def test_chromatic_red_complement_uses_adaptive_lightness():
    """Mid-L red skin: bg is cyan (complement) with sat*0.60 and L = 1 - skin_L."""
    skin = QColor(214, 49, 49)  # vivid red, L ~ 0.52
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, skin_s, skin_l, _ = skin.getHslF()
    h, s, l, _ = bg.getHslF()
    assert 0.45 < h < 0.55, f"expected hue near 0.5 (cyan), got {h}"
    assert abs(s - skin_s * 0.60) < 0.02, f"expected sat = skin_s * 0.60, got {s}"
    assert abs(l - (1.0 - skin_l)) < 0.02, f"expected L = 1 - skin_L, got {l}"


def test_chromatic_blue_complement_uses_adaptive_lightness():
    """Mid-L blue skin: bg is orange (complement) with adaptive L."""
    skin = QColor(31, 78, 184)  # vivid blue, L ~ 0.42
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, skin_l, _ = skin.getHslF()
    h, _, l, _ = bg.getHslF()
    # Blue hue ~0.6, complement ~0.1 (orange).
    assert 0.05 < h < 0.20, f"expected hue near 0.1 (orange), got {h}"
    assert abs(l - (1.0 - skin_l)) < 0.02, f"expected L = 1 - skin_L, got {l}"


def test_pale_pink_uses_dark_complement_regression():
    """Kubuntu pink regression: pale pink (L ~ 0.87) must produce a
    visibly darker bg, not another pale pastel. The clamp floor kicks in
    here because 1 - 0.87 = 0.13 falls below the 0.18 minimum."""
    skin = QColor(245, 200, 230)  # pale pink, L ~ 0.87
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, skin_l, _ = skin.getHslF()
    _, _, bg_l, _ = bg.getHslF()
    delta = skin_l - bg_l
    assert delta >= 0.40, (
        f"pale-skin bg must be significantly darker than the silhouette; "
        f"skin L={skin_l:.2f}, bg L={bg_l:.2f}, delta={delta:.2f}"
    )


def test_achromatic_dark_skin_gets_light_bg():
    """Near-black skin (L ~ 0.23) inverts to bg L ~ 0.77."""
    skin = QColor(58, 58, 58)
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, s, l, _ = bg.getHslF()
    assert s < 0.10, f"achromatic bg should be grayscale, got sat {s}"
    assert l > 0.70, f"dark skin should get light bg, got lightness {l}"


def test_achromatic_light_skin_gets_dark_bg():
    """Near-white skin (L ~ 0.88) inverts to bg L = 0.18 (clamp floor)."""
    skin = QColor(224, 224, 224)
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, s, l, _ = bg.getHslF()
    assert s < 0.10, f"achromatic bg should be grayscale, got sat {s}"
    assert l < 0.30, f"light skin should get dark bg, got lightness {l}"


def test_clamp_floor_at_near_white_chromatic_skin():
    """Skin L = 0.99 would invert to bg L = 0.01; clamp floor pins at 0.18."""
    skin = QColor.fromHslF(0.5, 0.6, 0.99)
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, bg_l, _ = bg.getHslF()
    assert 0.17 < bg_l < 0.20, (
        f"clamp floor should pin bg L near 0.18, got {bg_l:.3f}"
    )


def test_clamp_ceiling_at_near_black_chromatic_skin():
    """Skin L = 0.01 would invert to bg L = 0.99; clamp ceiling pins at 0.85."""
    skin = QColor.fromHslF(0.5, 0.6, 0.01)
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, bg_l, _ = bg.getHslF()
    assert 0.84 < bg_l < 0.86, (
        f"clamp ceiling should pin bg L near 0.85, got {bg_l:.3f}"
    )


def test_saturation_multiplier_is_consistent():
    """Chromatic bg saturation (HSL) is always skin saturation * 0.60."""
    for skin_sat in (0.30, 0.50, 0.80):
        skin = QColor.fromHslF(0.0, skin_sat, 0.50)
        bg = cc_badge_paint.complementary_bg_color(skin)
        _, bg_s, _, _ = bg.getHslF()
        expected = skin_sat * 0.60
        assert abs(bg_s - expected) < 0.02, (
            f"skin sat {skin_sat} -> expected bg sat {expected}, got {bg_s}"
        )
