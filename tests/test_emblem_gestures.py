"""_Emblem routes left-click -> menu_requested (open the wheel) and right-click
-> toggle_requested (quick mode-toggle), while a drag suppresses both. Also
exposes disc_diameter().

Run (NEVER the whole tests/ dir):
    env TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      python3 -m pytest tests/test_emblem_gestures.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _emblem(qapp):
    from tabs.multitoon._compact_layout import _Emblem
    e = _Emblem()
    e.set_interactive(True)
    e._dragging = False
    return e


def _release(emblem, button):
    pos = QPoint(10, 10)
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos),
                     QPointF(emblem.mapToGlobal(pos)),
                     button, button, Qt.NoModifier)
    emblem.mouseReleaseEvent(ev)


def _wire(emblem):
    seen = {"menu": [], "toggle": []}
    emblem.menu_requested.connect(lambda: seen["menu"].append(1))
    emblem.toggle_requested.connect(lambda: seen["toggle"].append(1))
    return seen


def test_left_click_opens_the_wheel(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.LeftButton)
    assert seen["menu"] == [1]
    assert seen["toggle"] == []
    e.deleteLater()


def test_right_click_quick_toggles(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.RightButton)
    assert seen["toggle"] == [1]
    assert seen["menu"] == []
    e.deleteLater()


def test_drag_suppresses_both(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    e._dragging = True               # a drag was in progress
    _release(e, Qt.LeftButton)
    e._dragging = True               # re-arm: a single drag covers both buttons
    _release(e, Qt.RightButton)
    assert seen["toggle"] == [] and seen["menu"] == []
    e.deleteLater()


def test_other_button_is_noop(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.MiddleButton)     # non-left/right = no-op
    assert seen["toggle"] == [] and seen["menu"] == []
    e.deleteLater()


def test_context_menu_signal_is_gone(qapp):
    e = _emblem(qapp)
    assert not hasattr(e, "context_menu_requested")
    e.deleteLater()


def test_disc_diameter_returns_disc(qapp):
    e = _emblem(qapp)
    assert e.disc_diameter() == float(e._d)
    e.deleteLater()


def test_emblem_press_depresses_and_click_triggers_ripple():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from tabs.multitoon._compact_layout import _Emblem
    QApplication.instance() or QApplication([])
    e = _Emblem()
    e.set_interactive(True)
    c = e.width() / 2.0
    e.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(c, c),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert e.get_press_scale() < 1.0
    assert e._ripple_active is False
    fired = []
    e.menu_requested.connect(lambda: fired.append(1))
    e.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(c, c),
                                    Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert fired == [1]
    assert e._ripple_active is True


def test_emblem_drag_does_not_ripple():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from tabs.multitoon._compact_layout import _Emblem
    QApplication.instance() or QApplication([])
    e = _Emblem()
    e.set_interactive(True)
    c = e.width() / 2.0
    e.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(c, c),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    moved = []
    e.move_requested.connect(lambda: moved.append(1))
    far = QPointF(c + 60, c + 60)
    e.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, far,
                                 Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    e.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, far,
                                    Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert moved == [1]
    assert e._ripple_active is False


def test_emblem_paint_with_press_and_ripple_does_not_crash():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from tabs.multitoon._compact_layout import _Emblem
    QApplication.instance() or QApplication([])
    e = _Emblem()
    e.set_press_scale(0.92)
    e._ripple_active = True
    e._ripple = 0.5
    pm = QPixmap(e.width(), e.height())
    p = QPainter(pm); e.render(p, QPoint(0, 0)); p.end()
