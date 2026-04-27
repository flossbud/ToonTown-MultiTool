"""Tests for utils.theme_manager typography helpers."""

from utils.theme_manager import font_role, TYPOGRAPHY, LIGHT_THEME


def test_font_role_known_roles_return_ints():
    for role in ("display", "title", "body", "label", "caption"):
        size = font_role(role)
        assert isinstance(size, int)
        assert 8 <= size <= 32, f"role={role} size={size} out of plausible range"


def test_font_role_scale_is_monotonic():
    # display > title > body > label > caption
    sizes = [font_role(r) for r in ("display", "title", "body", "label", "caption")]
    assert sizes == sorted(sizes, reverse=True), f"non-monotonic scale: {sizes}"


def test_font_role_unknown_falls_back_to_body():
    assert font_role("nonexistent") == font_role("body")


def test_typography_dict_has_canonical_roles():
    assert {"display", "title", "body", "label", "caption"} <= set(TYPOGRAPHY.keys())
