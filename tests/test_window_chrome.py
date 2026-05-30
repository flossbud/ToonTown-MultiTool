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


from PySide6.QtWidgets import QMainWindow, QFrame


class _FakeWindow(QMainWindow):
    """Stand-in main window that records the chrome calls."""
    def __init__(self):
        super().__init__()
        self.calls = []
    def showMinimized(self): self.calls.append("min")
    def showMaximized(self): self.calls.append("max")
    def showNormal(self): self.calls.append("normal")
    def close(self): self.calls.append("close"); return True


def test_controller_builds_three_named_controls(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = _FakeWindow()
    header = QFrame(win)
    ctl = WindowChromeController(win, header)
    assert ctl.btn_min.objectName() == "win_ctl_min"
    assert ctl.btn_max.objectName() == "win_ctl_max"
    assert ctl.btn_close.objectName() == "win_ctl_close"
    assert ctl.btn_min._dot_color == QColor("#4aa3ff")
    assert ctl.btn_max._dot_color == QColor("#0077ff")
    assert ctl.btn_close._dot_color == QColor("#ff5f56")


def test_controls_invoke_window_methods(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = _FakeWindow()
    ctl = WindowChromeController(win, QFrame(win))
    ctl.btn_min.click()
    ctl.btn_close.click()
    assert win.calls == ["min", "close"]


def test_maximize_toggles_and_swaps_glyph(qapp):
    from utils.widgets.window_chrome import WindowChromeController, maximize_glyph
    win = _FakeWindow()
    ctl = WindowChromeController(win, QFrame(win))
    ctl._sync_window_state(is_maximized=True)
    assert ctl.btn_max._glyph == maximize_glyph(True)
    ctl._sync_window_state(is_maximized=False)
    assert ctl.btn_max._glyph == maximize_glyph(False)
