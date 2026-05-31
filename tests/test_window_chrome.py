import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QSize, QPoint
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


from PySide6.QtWidgets import QMainWindow, QFrame, QWidget


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
    assert ctl.btn_min._dot_color == QColor("#febc2e")
    assert ctl.btn_max._dot_color == QColor("#28c840")
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


def test_press_near_edge_from_central_child_routes_to_resize(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = _FakeWindow(); win.resize(575, 770)
    header = QFrame(win)
    ctl = WindowChromeController(win, header)
    content = QWidget(win)  # a central child that covers the window
    action = ctl._press_action(content, QPoint(573, 768))  # bottom-right corner
    assert action is not None and action[0] == "resize"


def test_press_on_header_interior_routes_to_move(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = _FakeWindow(); win.resize(575, 770)
    header = QFrame(win)
    ctl = WindowChromeController(win, header)
    assert ctl._press_action(header, QPoint(300, 40)) == ("move", None)


def test_press_on_control_button_is_ignored(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = _FakeWindow(); win.resize(575, 770)
    header = QFrame(win)
    ctl = WindowChromeController(win, header)
    assert ctl._press_action(ctl.btn_close, QPoint(560, 12)) is None


def test_traffic_dot_diameter_is_16_and_glyph_scales():
    from utils.widgets.window_chrome import _TrafficDot
    dot = _TrafficDot("#febc2e", "-", "#7a4e00", "Minimize")
    assert dot._VISUAL_DIAMETER == 16
    # The dot derives its glyph size from its diameter (not a hardcoded value),
    # so paintEvent can't silently regress to the old fixed 9px.
    assert dot._glyph_pixel_size() == 11
    big = _TrafficDot("#febc2e", "-", "#7a4e00", "Minimize")
    big._VISUAL_DIAMETER = 30
    assert big._glyph_pixel_size() > dot._glyph_pixel_size()


def test_controller_buttons_use_traffic_light_colors(qapp):
    from PySide6.QtWidgets import QMainWindow, QFrame
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow()
    header = QFrame()
    c = WindowChromeController(win, header)
    # dot fills
    assert c.btn_min._dot_color.name() == "#febc2e"
    assert c.btn_max._dot_color.name() == "#28c840"
    assert c.btn_close._dot_color.name() == "#ff5f56"
    # glyph tints (darker shades, not white)
    assert c.btn_min._glyph_color.name() == "#7a4e00"
    assert c.btn_max._glyph_color.name() == "#0c5a1e"
    assert c.btn_close._glyph_color.name() == "#7a1410"


def test_controller_inits_maximized_state_from_window(qapp):
    from PySide6.QtWidgets import QMainWindow, QFrame
    from utils.widgets.window_chrome import WindowChromeController, maximize_glyph

    # Deterministic: force the window to report maximized so the test fails
    # against the old hardcoded `_is_maximized = False` (offscreen does not
    # reliably honor showMaximized()).
    win = QMainWindow()
    win.isMaximized = lambda: True  # monkeypatch the instance
    header = QFrame()
    c = WindowChromeController(win, header)
    assert c._is_maximized is True
    assert c.btn_max._glyph == maximize_glyph(True)


def test_dot_hover_press_targets(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)  # instant: value == target
    from utils.widgets.window_chrome import _TrafficDot
    d = _TrafficDot("#febc2e", "−", "#7a4e00", "Minimize")
    assert d.dot_scale == 1.0 and d.brightness == 1.0
    d._set_dot_hovered(True)
    assert d.dot_scale == 1.10 and round(d.brightness, 2) == 1.18
    d._set_pressed(True)            # press overrides hover
    assert d.dot_scale == 0.94 and round(d.brightness, 2) == 0.85
    d._set_pressed(False); d._set_dot_hovered(False)
    assert d.dot_scale == 1.0 and d.brightness == 1.0


def test_dot_reduced_motion_no_animation(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from utils.widgets.window_chrome import _TrafficDot
    d = _TrafficDot("#28c840", "□", "#0c5a1e", "Maximize")
    d._set_dot_hovered(True)
    assert d._scale_anim.state() != d._scale_anim.State.Running
    assert d.dot_scale == 1.10
