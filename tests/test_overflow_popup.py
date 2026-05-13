"""Tests for OverflowPopup — custom QFrame popup replacing QMenu."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QToolButton

from utils.widgets.overflow_popup import OverflowPopup


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_popup_starts_hidden(qapp):
    pop = OverflowPopup()
    assert not pop.isVisible()


def test_add_action_creates_clickable_row(qapp):
    pop = OverflowPopup()
    called = []
    pop.add_action("View Logs", lambda: called.append("v"))
    assert len(pop.rows) == 1
    # Simulate click
    pop.rows[0].clicked.emit()
    assert called == ["v"]


def test_show_at_positions_below_anchor(qapp):
    pop = OverflowPopup()
    pop.add_action("View Logs", lambda: None)
    anchor = QToolButton()
    anchor.setFixedSize(34, 34)
    anchor.move(500, 100)
    anchor.show()
    qapp.processEvents()

    pop.show_at(anchor)
    qapp.processEvents()
    # Popup top should be at/near anchor bottom.
    expected_y = anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    assert abs(pop.pos().y() - expected_y) <= 4
