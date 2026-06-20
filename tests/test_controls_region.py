# tests/test_controls_region.py
import sys
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from utils.overlay.region import controls_region


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def test_controls_region_unions_scaled_device_rects(qt_app):
    base = [QRect(0, 0, 10, 10), QRect(20, 0, 10, 10)]
    region = controls_region(base, scale=2.0, dpr=1.0)
    # Two disjoint 20x20 device rects at x=0 and x=40.
    assert region.contains(QRect(0, 0, 20, 20))
    assert region.contains(QRect(40, 0, 20, 20))
    assert not region.contains(QRect(25, 0, 1, 1))  # the gap is a hole


def test_controls_region_applies_dpr(qt_app):
    region = controls_region([QRect(0, 0, 10, 10)], scale=1.0, dpr=2.0)
    assert region.boundingRect() == QRect(0, 0, 20, 20)


def test_controls_region_empty_is_empty(qt_app):
    assert controls_region([], scale=1.0, dpr=1.0).isEmpty()
