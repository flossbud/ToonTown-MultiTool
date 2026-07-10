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


def test_apply_v2_theme_updates_paint_attrs(qapp):
    """OverflowPopup.apply_v2_theme must update the background and border
    colors used by paintEvent so theme switches don't leave the popup
    painted with stale literals."""
    from PySide6.QtGui import QColor
    pop = OverflowPopup()
    pop.apply_v2_theme(False)
    assert pop._bg_color == QColor(255, 255, 255, 247)
    assert pop._border_color == QColor("#cbd5e1")
    pop.apply_v2_theme(True)
    assert pop._bg_color == QColor(30, 30, 30, 235)
    assert pop._border_color == QColor(255, 255, 255, 28)


def test_hide_emits_closed(qapp):
    """Every dismissal path funnels through hide(); the closed signal must
    fire so the trigger button drops its [open=\"true\"] state even on
    click-outside/Esc dismissals that never pass through the toggle."""
    pop = OverflowPopup()
    got = []
    pop.closed.connect(lambda: got.append(True))
    pop.show()
    pop.hide()
    assert got == [True]
