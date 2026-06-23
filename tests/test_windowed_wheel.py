import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="run under QT_QPA_PLATFORM=offscreen",
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fixture():
    """A parent container with a small stub emblem inside it."""
    from PySide6.QtWidgets import QWidget
    parent = QWidget(); parent.resize(800, 600)
    emblem = QWidget(parent); emblem.resize(120, 120); emblem.move(340, 240)
    return parent, emblem


def test_host_builds_windowed_three_spoke_menu():
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    assert host.menu.state == "main"
    assert sorted(host.menu.reveal_order("main")) == sorted(
        ["accounts", "transparent", "close"])


def test_host_dismiss_emits_closed_once_and_is_idempotent():
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    closed = []
    host.closed.connect(lambda: closed.append(1))
    host.dismiss()
    host.dismiss()                       # idempotent
    assert closed == [1]


def test_menu_close_request_dismisses_host():
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    closed = []
    host.closed.connect(lambda: closed.append(1))
    host.menu.close_requested.emit()     # Back / Esc / idle / all-launched path
    assert closed == [1]


def test_show_centered_places_dim_under_emblem():
    """The dim backdrop is a sibling of the emblem, centered on it, and stacked
    just BELOW it (so the emblem stays in front of the dim)."""
    from utils.overlay.radial_menu import RadialDimWidget
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    emblem.raise_()                          # emblem on top, as the tab arranges it
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    host.show_centered()
    dim = host._dim
    assert isinstance(dim, RadialDimWidget)
    assert dim.parentWidget() is emblem.parentWidget()       # sibling of the emblem
    dc, ec = dim.geometry().center(), emblem.geometry().center()
    # Centered on the emblem (within 1px: QRect.center() floors on even sizes).
    assert abs(dc.x() - ec.x()) <= 1 and abs(dc.y() - ec.y()) <= 1
    # Stacked below the emblem: the parent's child order is its stacking order, so
    # the dim must come before the emblem (lower) after stackUnder().
    kids = parent.children()
    assert kids.index(dim) < kids.index(emblem)


def test_dismiss_tears_down_the_dim():
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    host.show_centered()
    assert host._dim is not None
    host.dismiss()
    assert host._dim is None                 # gone with the host


def test_host_press_click_away_dismisses():
    _app()
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    closed = []
    host.closed.connect(lambda: closed.append(1))
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    host.mousePressEvent(ev)             # a press that missed the menu
    assert closed == [1]
