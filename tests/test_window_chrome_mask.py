import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def test_rounded_region_excludes_corner_includes_center(app):
    from utils.window_chrome_mask import rounded_region
    r = rounded_region(100, 80, 16)
    assert isinstance(r, QRegion)
    assert r.contains(QPoint(50, 40))      # center is inside
    assert not r.contains(QPoint(0, 0))    # rounded-off corner is outside


def test_zero_radius_is_full_rect(app):
    from utils.window_chrome_mask import rounded_region
    r = rounded_region(40, 30, 0)
    assert r.contains(QPoint(0, 0))        # square corners -> full rect
    assert r.boundingRect().width() == 40
