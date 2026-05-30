import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from utils.widgets.window_chrome import resize_edge_for_pos, maximize_glyph


def test_no_edge_in_center():
    assert resize_edge_for_pos(100, 100, 575, 770, margin=6) is None


def test_left_edge():
    assert resize_edge_for_pos(2, 400, 575, 770, margin=6) == Qt.Edge.LeftEdge


def test_bottom_right_corner():
    e = resize_edge_for_pos(573, 768, 575, 770, margin=6)
    assert e == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge)


def test_top_edge():
    assert resize_edge_for_pos(300, 1, 575, 770, margin=6) == Qt.Edge.TopEdge


def test_maximize_glyph_swaps_on_state():
    assert maximize_glyph(is_maximized=False) == "□"   # WHITE SQUARE
    assert maximize_glyph(is_maximized=True) == "❐"    # restore glyph


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_traffic_dot_properties(qapp):
    from utils.widgets.window_chrome import _TrafficDot
    dot = _TrafficDot(dot_color="#ff5f56", glyph="×", glyph_color="#ffcecb",
                      accessible_name="Close")
    assert dot.size() == QSize(22, 22)            # comfortable hit area
    assert dot.accessibleName() == "Close"
    assert dot.toolTip() == "Close"
    assert dot._dot_color == QColor("#ff5f56")
    assert dot._glyph == "×"
