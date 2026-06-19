import sys, pytest
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="x11 only")
from PySide6.QtGui import QRegion
from PySide6.QtCore import QRect
from utils.overlay.x11_backend import region_to_rects

def test_region_to_rects_round_trips():
    region = QRegion(QRect(10, 20, 30, 40)).united(QRegion(QRect(100, 0, 5, 5)))
    rects = region_to_rects(region)
    assert (10, 20, 30, 40) in rects
    assert (100, 0, 5, 5) in rects

def test_empty_region_is_empty_list():
    assert region_to_rects(QRegion()) == []
