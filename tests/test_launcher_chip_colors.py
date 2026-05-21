"""Tests for the brand-color gradient tokens used by the picker chips."""

from utils.launcher_chip import (
    LAUNCHER_CHIP_LABEL,
    LAUNCHER_CHIP_COLOR,
    chip_style_for,
)


def test_every_label_has_a_color():
    """Every slug in LAUNCHER_CHIP_LABEL must have a matching color."""
    missing = set(LAUNCHER_CHIP_LABEL) - set(LAUNCHER_CHIP_COLOR)
    assert not missing, f"slugs missing colors: {missing}"


def test_compat_only_slugs_have_colors():
    """AUTO and PROTON are not real launchers but the compat picker uses them."""
    assert "auto" in LAUNCHER_CHIP_COLOR
    assert "proton" in LAUNCHER_CHIP_COLOR


def test_color_tuples_are_pairs_of_hex_strings():
    for slug, pair in LAUNCHER_CHIP_COLOR.items():
        assert isinstance(pair, tuple) and len(pair) == 2, slug
        for stop in pair:
            assert isinstance(stop, str) and stop.startswith("#"), (slug, stop)
            assert len(stop) == 7, (slug, stop)  # #rrggbb


def test_chip_style_for_returns_qss_gradient_for_known_slug():
    qss = chip_style_for("wine")
    assert "qlineargradient" in qss
    assert "#d04545" in qss
    assert "#7a2222" in qss


def test_chip_style_for_unknown_slug_returns_fallback_gray():
    """Unknown slugs render with a neutral fallback so adding a launcher to
    LAUNCHER_CHIP_LABEL without updating LAUNCHER_CHIP_COLOR never crashes."""
    qss = chip_style_for("never-heard-of-it")
    assert "qlineargradient" in qss
    # Fallback uses a neutral mid-gray pair.
    assert "#4b5563" in qss or "#6a7280" in qss
