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
    # reduced motion must start NONE of the three animations
    assert d._scale_anim.state() != d._scale_anim.State.Running
    assert d._bright_anim.state() != d._bright_anim.State.Running
    assert d._glyph_anim.state() != d._glyph_anim.State.Running
    assert d.dot_scale == 1.10


def test_dot_release_clears_pressed_and_emits_clicked(qapp):
    # A full press+release must still emit `clicked` AND clear _pressed; the
    # release clears _pressed BEFORE super() so a close-on-click slot can delete
    # the widget without a use-after-free.
    from PySide6.QtTest import QTest
    from utils.widgets.window_chrome import _TrafficDot
    d = _TrafficDot("#ff5f56", "×", "#7a1410", "Close"); d.resize(22, 22)
    fired = []
    d.clicked.connect(lambda: fired.append(True))
    QTest.mouseClick(d, Qt.LeftButton)
    assert fired == [True]
    assert d._pressed is False


def test_cluster_hover_reveals_all_glyphs(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtWidgets import QMainWindow, QFrame
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    c = WindowChromeController(win, header)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b.glyph_opacity == 0.0          # hidden at rest
    c.set_cluster_hovered(True)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b.glyph_opacity == 1.0
    c.set_cluster_hovered(False)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b.glyph_opacity == 0.0


def test_cluster_wraps_dots(qapp):
    from PySide6.QtWidgets import QMainWindow, QFrame
    from utils.widgets.window_chrome import WindowChromeController, _TrafficCluster
    win = QMainWindow(); header = QFrame()
    c = WindowChromeController(win, header)
    assert isinstance(c._cluster, _TrafficCluster)
    assert c._cluster.width() == 3 * 22 + 2 * 8
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b.parent() is c._cluster


def test_dot_press_routes_to_none_gap_press_moves(qapp):
    # reparenting into the cluster must NOT break drag/click routing
    from PySide6.QtWidgets import QMainWindow, QFrame
    from PySide6.QtCore import QPoint
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); win.resize(575, 770); header = QFrame(win)
    c = WindowChromeController(win, header)
    assert c._press_action(c.btn_close, QPoint(560, 12)) is None      # dot press = click
    assert c._press_action(c._cluster, QPoint(540, 12)) == ("move", None)  # gap/cluster press = move


def test_local_hover_scope(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtWidgets import QMainWindow, QFrame
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    c = WindowChromeController(win, header)
    c.btn_max._set_dot_hovered(True)
    assert c.btn_max.dot_scale == 1.10
    assert c.btn_min.dot_scale == 1.0 and c.btn_close.dot_scale == 1.0  # siblings unaffected


def test_cluster_enter_leave_drives_reveal(qapp, monkeypatch):
    # Exercise the REAL _TrafficCluster.enterEvent/leaveEvent (not the controller
    # method directly), so broken hover delivery would fail this.
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtCore import QPointF, QEvent
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame(win)
    c = WindowChromeController(win, header)
    pt = QPointF(1, 1)
    c._cluster.enterEvent(QEnterEvent(pt, pt, pt))
    assert c.btn_min.glyph_opacity == 1.0 and c.btn_close.glyph_opacity == 1.0
    c._cluster.leaveEvent(QEvent(QEvent.Leave))
    assert c.btn_min.glyph_opacity == 0.0 and c.btn_close.glyph_opacity == 0.0


def test_cluster_lays_dots_left_to_right(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame(win)
    c = WindowChromeController(win, header)
    c._cluster.layout().activate()
    assert c.btn_min.x() == 0
    assert c.btn_max.x() == 30      # 22px dot + 8px gap
    assert c.btn_close.x() == 60


def test_reposition_places_cluster_top_right(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame(win); header.resize(575, 112)
    c = WindowChromeController(win, header)
    c.reposition()
    assert c._cluster.x() == 575 - 12 - 82
    assert c._cluster.y() == 12


def test_window_focus_propagates_to_dots(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    c = WindowChromeController(win, header)
    c.set_window_focused(False)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b._window_focused is False
    c.set_window_focused(True)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b._window_focused is True


def test_set_theme_pushes_inactive_colors(qapp):
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    c = WindowChromeController(win, header)
    c.set_theme(is_dark=False)
    for b in (c.btn_min, c.btn_max, c.btn_close):   # fan-out to ALL three
        assert b._inactive_dot == QColor("#b8bcc2")
        assert b._inactive_glyph == QColor("#8b9098")
    c.set_theme(is_dark=True)
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b._inactive_dot == QColor("#5a5d63")
        assert b._inactive_glyph == QColor("#33353a")


def test_deactivate_event_dims_dots(qapp):
    # the controller's eventFilter must DIM on WindowDeactivate (not merely match
    # whatever isActiveWindow() already returns)
    from PySide6.QtCore import QEvent
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    win.isActiveWindow = lambda: False
    c = WindowChromeController(win, header)
    c.set_window_focused(True)
    c.eventFilter(win, QEvent(QEvent.WindowDeactivate))
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b._window_focused is False


def test_activate_event_restores_dots(qapp):
    # symmetric: WindowActivate must restore focus when the window reports active
    from PySide6.QtCore import QEvent
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame()
    win.isActiveWindow = lambda: True
    c = WindowChromeController(win, header)
    c.set_window_focused(False)
    c.eventFilter(win, QEvent(QEvent.WindowActivate))
    for b in (c.btn_min, c.btn_max, c.btn_close):
        assert b._window_focused is True


def _box_vs_dot_centers(glyph, scale):
    """Isolate the box-glyph ink (diff vs dot-only) and the dot; return
    (box_cx, box_cy, dot_cx, dot_cy) bbox centers under the SAME pixel
    convention so they're directly comparable."""
    from utils.widgets.window_chrome import _TrafficDot
    def grab(g):
        b = _TrafficDot("#28c840", g, "#0c5a1e", "Maximize"); b.resize(22, 22)
        b._window_focused = True; b._glyph_opacity = 1.0; b._dot_scale = scale
        return b.grab().toImage()
    withg = grab(glyph); without = grab("")
    gxs, gys, dxs, dys = [], [], [], []
    for y in range(22):
        for x in range(22):
            a = withg.pixelColor(x, y); o = without.pixelColor(x, y)
            if abs(a.red()-o.red()) + abs(a.green()-o.green()) + abs(a.blue()-o.blue()) > 20:
                gxs.append(x); gys.append(y)
            if o.alpha() > 30:
                dxs.append(x); dys.append(y)
    assert gxs and dxs, "no glyph ink or no dot pixels detected"
    return ((min(gxs)+max(gxs))/2.0, (min(gys)+max(gys))/2.0,
            (min(dxs)+max(dxs))/2.0, (min(dys)+max(dys))/2.0)


def test_box_glyphs_centered_on_dot(qapp, monkeypatch):
    # The maximize □ AND restore ❐ must be centered on the dot, horizontally
    # (<=0.25) and vertically (<=0.5), at rest and hover scale. This is the
    # regression guard for the repeated off-center bugs (now vector-drawn).
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    for glyph in (maximize_glyph(False), maximize_glyph(True)):
        for scale in (1.0, 1.10):
            bx, by, dx, dy = _box_vs_dot_centers(glyph, scale)
            assert abs(bx - dx) <= 0.25, f"{glyph!r} scale {scale}: x off {bx-dx:+.2f} (box {bx} dot {dx})"
            assert abs(by - dy) <= 0.5, f"{glyph!r} scale {scale}: y off {by-dy:+.2f} (box {by} dot {dy})"


def test_box_glyph_renders_at_partial_opacity(qapp, monkeypatch):
    # stroke-only box glyphs must composite fine mid-fade (no occlusion-fill
    # bleed); just assert rendering the restore glyph at 0.5 opacity is stable.
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from utils.widgets.window_chrome import _TrafficDot
    b = _TrafficDot("#28c840", maximize_glyph(True), "#0c5a1e", "Maximize"); b.resize(22, 22)
    b._window_focused = True; b._glyph_opacity = 0.5
    img = b.grab().toImage()         # must not raise
    assert img.width() == 22


def test_header_app_icon_rest_opacity(qapp):
    from PySide6.QtGui import QIcon
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = _HeaderAppIcon(QIcon())
    assert icon.icon_opacity == 0.75
    assert icon._active is False
    assert icon.size().width() == 36 and icon.size().height() == 36


def test_header_app_icon_hover_brightens(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)  # instant: value == target
    from PySide6.QtGui import QIcon
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = _HeaderAppIcon(QIcon())
    icon._set_hovered(True)
    assert icon.icon_opacity == 1.0
    icon._set_hovered(False)
    assert icon.icon_opacity == 0.75


def test_header_app_icon_active_holds_lit_through_hover_out(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtGui import QIcon
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = _HeaderAppIcon(QIcon())
    icon.set_active(True)
    assert icon.icon_opacity == 1.0
    icon._set_hovered(True); icon._set_hovered(False)   # hover-out while active
    assert icon.icon_opacity == 1.0                     # stays lit
    icon.set_active(False)
    assert icon.icon_opacity == 0.75


def test_header_app_icon_reduced_motion_no_animation(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtGui import QIcon
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = _HeaderAppIcon(QIcon())
    icon._set_hovered(True)
    assert icon._op_anim.state() != icon._op_anim.State.Running
    assert icon.icon_opacity == 1.0


def test_press_on_header_button_not_routed_to_move(qapp):
    # Any QAbstractButton inside the header must NOT be turned into a window
    # move/resize (it handles its own click). The header background still does.
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMainWindow, QFrame, QPushButton
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame(); win.setCentralWidget(header)
    win.resize(575, 300)
    c = WindowChromeController(win, header)
    btn = QPushButton(header)             # a non-_TrafficDot header button
    # interior point (away from resize edges)
    assert c._press_action(btn, QPoint(100, 100)) is None
    # the header background itself is still draggable
    assert c._press_action(header, QPoint(100, 100)) == ("move", None)


def test_doubleclick_on_header_button_does_not_maximize(qapp, monkeypatch):
    # The dblclick guard must also exclude buttons: double-clicking a header
    # QAbstractButton must NOT toggle maximize, while the header bg still does.
    from PySide6.QtCore import QPoint, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QMainWindow, QFrame, QPushButton
    from utils.widgets.window_chrome import WindowChromeController
    win = QMainWindow(); header = QFrame(); win.setCentralWidget(header)
    win.resize(575, 300)
    c = WindowChromeController(win, header)
    calls = []
    monkeypatch.setattr(c, "_toggle_max_restore", lambda: calls.append(True))
    btn = QPushButton(header)

    def dblclick(obj, local):
        ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(local), QPointF(local),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        c.eventFilter(obj, ev)

    dblclick(btn, QPoint(5, 5))            # button: must NOT maximize
    assert calls == []
    dblclick(header, QPoint(100, 100))     # header bg: must maximize
    assert calls == [True]


def test_window_deactivate_does_not_dim_app_icon(qapp, monkeypatch):
    # The header app icon ignores window focus (unlike the traffic dots, which
    # grey out on deactivate). It has no set_window_focused, and a
    # WindowDeactivate delivered to it must not change its opacity.
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QIcon
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = _HeaderAppIcon(QIcon())
    assert icon.icon_opacity == 0.75
    assert not hasattr(icon, "set_window_focused")       # no focus handling
    QApplication.sendEvent(icon, QEvent(QEvent.WindowDeactivate))
    assert icon.icon_opacity == 0.75                     # focus change does not dim it
    icon._set_hovered(True)                              # sanity: opacity IS responsive
    assert icon.icon_opacity == 1.0
