"""Tests for utils.layout helpers."""

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from PySide6.QtCore import Qt

from utils.layout import clamp_centered


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_clamp_centered_sets_max_width(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    clamp_centered(layout, child, 480)
    assert child.maximumWidth() == 480


def test_clamp_centered_uses_horizontal_center_alignment(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    clamp_centered(layout, child, 720)
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is child:
            assert item.alignment() & Qt.AlignHCenter
            return
    pytest.fail("child was not added to the layout")


def test_clamp_centered_returns_widget_for_chaining(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    result = clamp_centered(layout, child, 480)
    assert result is child


def test_status_indicator_constructs_and_renders(qapp):
    from tabs.multitoon._full_layout import _StatusIndicator
    from PySide6.QtGui import QPixmap

    w = _StatusIndicator()
    w.apply_theme("#2a2a30", "#3aaa5e", "#45454c")
    w.set_active(True)
    # Render to a pixmap to force a paintEvent
    pixmap = QPixmap(w.size())
    pixmap.fill(Qt.transparent)
    w.render(pixmap)
    assert not pixmap.isNull()
    assert pixmap.size().width() == 32
    assert pixmap.size().height() == 32
