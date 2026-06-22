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
