import pytest
from utils.theme_manager import get_set_card_styles, get_set_color


REQUIRED_KEYS = {
    "card_border", "card_grad_top", "card_grad_bottom",
    "stripe_edge", "stripe_center",
    "name_color",
    "badge_bg", "badge_text", "badge_ring",
    "head_divider",
}


def test_returns_all_required_keys():
    style = get_set_card_styles(0, is_dark=True)
    assert set(style.keys()) == REQUIRED_KEYS


def test_name_color_matches_lighter_variant_of_set_bg():
    from PySide6.QtGui import QColor
    bg, _ = get_set_color(0)
    expected = QColor(bg).lighter(135).name()
    assert get_set_card_styles(0, is_dark=True)["name_color"] == expected


def test_rgba_strings_use_set_color_rgb():
    # SET 1 (index 0) is #4A8FE7 -> rgb 74,143,231
    style = get_set_card_styles(0, is_dark=True)
    assert "74, 143, 231" in style["card_grad_top"]
    assert "74, 143, 231" in style["card_border"]
    assert "rgba(" in style["card_grad_top"]


def test_card_grad_opacity_top_higher_than_bottom():
    style = get_set_card_styles(0, is_dark=True)
    # Pull the alpha out of the rgba(r, g, b, a) strings
    def alpha(s):
        return float(s.rsplit(",", 1)[1].strip(" )"))
    assert alpha(style["card_grad_top"]) > alpha(style["card_grad_bottom"])


def test_out_of_range_index_returns_fallback():
    style = get_set_card_styles(99, is_dark=True)
    assert set(style.keys()) == REQUIRED_KEYS  # same shape, just gray fallback
