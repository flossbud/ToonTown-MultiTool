"""v2 icon makers + Switch 44x24 restyle."""
import pytest
from PySide6.QtWidgets import QApplication

from utils.icon_factory import (
    make_activity_icon, make_database_icon, make_download_icon,
    make_radio_waves_icon, make_sliders_icon, make_wrench_icon,
)
from utils.shared_widgets import Switch


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("maker", [
    make_sliders_icon, make_download_icon, make_activity_icon,
    make_database_icon, make_wrench_icon, make_radio_waves_icon,
])
def test_maker_returns_paintable_icon(app, maker):
    icon = maker(20)
    assert not icon.pixmap(20, 20).isNull()


def test_switch_v2_geometry(app):
    s = Switch(False)
    assert (s.width(), s.height()) == (50, 30)
    assert Switch.TRACK_W == 44 and Switch.TRACK_H == 24 and Switch.THUMB_D == 18


def test_switch_accent(app):
    s = Switch(True)
    s.set_accent("#ff9500", "#ffb04d")
    assert s._track_on == "#ff9500" and s._border_on == "#ffb04d"
