"""PortraitBadge - 46px ringed circle badge (glyph or logo variant)."""
import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.portrait_badge import PortraitBadge


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_fixed_size_and_glyph_variant(app):
    from utils.icon_factory import make_nav_gear
    b = PortraitBadge(accent_key="blue", icon=make_nav_gear(20, None))
    assert b.width() == 46 and b.height() == 46
    b.apply_theme(is_dark=True)
    assert not b.grab().isNull()          # paints without error


def test_logo_variant_missing_file_still_paints(app):
    b = PortraitBadge(logo_path="/nonexistent/logo.png")
    b.apply_theme(is_dark=False)
    assert not b.grab().isNull()


def test_unknown_accent_key_falls_back_to_blue(app):
    b = PortraitBadge(accent_key="nope")
    assert b._accent == {"c": "#0077ff", "b": "#3399ff"}
