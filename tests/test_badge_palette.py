"""Badge off endpoints + theme-parameterized pixel dim."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_dim_pixmap_params_default_matches_legacy(qapp):
    from utils.card_dim import dim_pixmap
    pm = QPixmap(4, 4); pm.fill(QColor("#4A8FE7"))
    assert dim_pixmap(pm).toImage() == dim_pixmap(pm, sat=0.45, bright=0.75).toImage()


def test_dim_pixmap_light_params_never_darken(qapp):
    from utils.card_dim import dim_pixmap
    pm = QPixmap(2, 2); pm.fill(QColor("#e6d35a"))
    img = dim_pixmap(pm, sat=0.35, bright=1.0).toImage()
    px = img.pixelColor(0, 0)
    lum_in = 0.3 * 230 + 0.59 * 211 + 0.11 * 90
    lum_out = 0.3 * px.red() + 0.59 * px.green() + 0.11 * px.blue()
    assert abs(lum_out - lum_in) <= 2      # luma preserved, no 0.75 darkening


def test_badge_dim_appearance_swaps_fallback_colors(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    w.resize(48, 48)
    w.set_colors("#101010", "#ffffff")
    w.set_dim_appearance(sat=0.35, bright=1.0,
                         bg_off=QColor("#e8ecf1"), ink_off=QColor("#98a6ba"))
    w.set_dim_progress(1.0)
    img = w._dimmed_pixmap().toImage()
    # (10, 34) is inside the fallback circle (r=22 around 24,24) but clear of
    # the centered slot-number glyph: it must read as paper - light, not dark.
    assert img.pixelColor(10, 34).lightness() > 200
    # ink_off must actually be consumed: an identical widget WITHOUT it keeps
    # the lit white ink for the glyph, so the dimmed renders must differ.
    v = ToonPortraitWidget(1)
    v.resize(48, 48)
    v.set_colors("#101010", "#ffffff")
    v.set_dim_appearance(sat=0.35, bright=1.0,
                         bg_off=QColor("#e8ecf1"), ink_off=None)
    v.set_dim_progress(1.0)
    assert v._dimmed_pixmap().toImage() != img


def test_badge_dim_appearance_default_is_legacy(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    a = ToonPortraitWidget(1); a.resize(48, 48); a.set_colors("#101010", "#ffffff")
    b = ToonPortraitWidget(1); b.resize(48, 48); b.set_colors("#101010", "#ffffff")
    b.set_dim_appearance()                      # explicit defaults
    assert a._dimmed_pixmap().toImage() == b._dimmed_pixmap().toImage()
