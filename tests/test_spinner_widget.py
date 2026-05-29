"""Spinner animates only while visible and paints without error."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_timer_runs_only_while_visible(qapp):
    from utils.shared_widgets import Spinner
    s = Spinner(14)
    assert not s._timer.isActive()
    s.show()
    QCoreApplication.processEvents()
    assert s._timer.isActive()
    s.hide()
    QCoreApplication.processEvents()
    assert not s._timer.isActive()
    s.deleteLater()


def test_advance_changes_angle(qapp):
    from utils.shared_widgets import Spinner
    s = Spinner(14)
    a0 = s._angle
    s._advance()
    assert s._angle != a0
    s.deleteLater()


def test_paint_does_not_raise(qapp):
    from utils.shared_widgets import Spinner
    s = Spinner(14)
    s.set_color("#8a9bb8")
    s.grab()  # forces a synchronous paintEvent
    s.deleteLater()
