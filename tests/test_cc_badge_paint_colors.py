"""Tests for the CC badge color helpers (background derivation)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from utils import cc_badge_paint


def test_chromatic_red_complement_pushes_to_dark_clamp_at_mid_lightness():
    """Mid-L red skin (L ~ 0.52) triggers the mid-L branch: bg goes to
    the dark clamp (0.18) so the silhouette stays visible against the
    background instead of vanishing into a same-L cyan."""
    skin = QColor(214, 49, 49)  # vivid red, L ~ 0.52
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, skin_s, skin_l, _ = skin.getHslF()
    h, s, l, _ = bg.getHslF()
    assert 0.45 < h < 0.55, f"expected hue near 0.5 (cyan), got {h}"
    assert abs(s - skin_s * 0.60) < 0.02, f"expected sat = skin_s * 0.60, got {s}"
    assert 0.17 < l < 0.20, (
        f"mid-L skin should push bg L to the dark clamp, got {l:.3f}"
    )


def test_chromatic_blue_complement_pushes_to_light_clamp_at_mid_lightness():
    """Mid-L blue skin (L ~ 0.42) is in the lower half of the clamp
    range, so the mid-L branch pushes bg to the bright clamp (0.85)."""
    skin = QColor(31, 78, 184)  # vivid blue, L ~ 0.42
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, skin_l, _ = skin.getHslF()
    h, _, l, _ = bg.getHslF()
    # Blue hue ~0.6, complement ~0.1 (orange).
    assert 0.05 < h < 0.20, f"expected hue near 0.1 (orange), got {h}"
    assert 0.84 < l < 0.86, (
        f"mid-L skin in lower clamp half should push bg L to the bright "
        f"clamp, got {l:.3f}"
    )


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


@pytest.mark.parametrize("skin_l", [0.40, 0.45, 0.50, 0.55, 0.60])
def test_mid_lightness_skin_produces_minimum_delta(skin_l):
    """For any skin whose lightness lies in the mid range, the bg must
    have at least 0.25 lightness delta from the skin so the silhouette
    stays visible against the circle."""
    skin = QColor.fromHslF(0.0, 0.6, skin_l)  # red-ish chromatic
    bg = cc_badge_paint.complementary_bg_color(skin)
    _, _, bg_l, _ = bg.getHslF()
    delta = abs(skin_l - bg_l)
    assert delta >= 0.25, (
        f"mid-L skin L={skin_l:.2f} produced bg L={bg_l:.3f} (delta={delta:.3f}); "
        f"want delta >= 0.25 for visible silhouette"
    )
