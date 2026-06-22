"""_Emblem routes right-click -> context_menu_requested(QPoint) and left-click ->
toggle_requested, while a drag suppresses both.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \\
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \\
      ./venv/bin/python -m pytest tests/test_emblem_context_menu.py -q
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
    seen = {"ctx": [], "toggle": []}
    emblem.context_menu_requested.connect(lambda p: seen["ctx"].append(p))
    emblem.toggle_requested.connect(lambda: seen["toggle"].append(1))
    return seen


def test_right_click_emits_context_menu_with_point(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.RightButton)
    assert len(seen["ctx"]) == 1
    assert isinstance(seen["ctx"][0], QPoint)
    assert seen["toggle"] == []
    e.deleteLater()


def test_left_click_emits_toggle_only(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.LeftButton)
    assert len(seen["toggle"]) == 1
    assert seen["ctx"] == []
    e.deleteLater()


def test_drag_suppresses_both(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    e._dragging = True               # a drag was in progress
    _release(e, Qt.LeftButton)
    e._dragging = True               # re-arm: a single drag covers both buttons
    _release(e, Qt.RightButton)
    assert seen["toggle"] == [] and seen["ctx"] == []
    e.deleteLater()


def test_other_button_is_noop(qapp):
    e = _emblem(qapp)
    seen = _wire(e)
    _release(e, Qt.MiddleButton)     # locked decision: non-left/right = no-op
    assert seen["toggle"] == [] and seen["ctx"] == []
    e.deleteLater()
