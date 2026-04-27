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


def test_full_layout_helper_imports_resolve(qapp):
    """Sanity: the new symbols added in Task 9 are importable."""
    from tabs.multitoon._full_layout import (
        _StatusIndicator, _FullToonCard, _make_ctrl_32
    )
    assert _StatusIndicator is not None
    assert _FullToonCard is not None
    assert callable(_make_ctrl_32)


def test_make_ctrl_32_sets_fixed_height_and_radius(qapp):
    """`_make_ctrl_32` is the shared baseliner for the controls row."""
    from PySide6.QtWidgets import QPushButton
    from tabs.multitoon._full_layout import _make_ctrl_32

    btn = QPushButton("Test")
    _make_ctrl_32(btn)
    assert btn.minimumHeight() == 32
    assert btn.maximumHeight() == 32
    assert "border-radius: 6px" in btn.styleSheet()


def test_clear_layout_removes_all_items(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from tabs.multitoon._layout_utils import clear_layout

    parent = QWidget()
    layout = QHBoxLayout(parent)
    btn1 = QPushButton("a", parent=parent)
    btn2 = QPushButton("b", parent=parent)
    layout.addWidget(btn1)
    layout.addWidget(btn2)
    layout.addStretch()
    assert layout.count() == 3

    clear_layout(layout)
    assert layout.count() == 0


def test_clear_layout_does_not_destroy_widgets(qapp):
    """Widgets are owned externally and must survive the clear."""
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from tabs.multitoon._layout_utils import clear_layout

    parent = QWidget()
    layout = QHBoxLayout(parent)
    btn = QPushButton("x", parent=parent)
    layout.addWidget(btn)

    clear_layout(layout)
    # Widget still exists; just no parent layout.
    assert btn is not None
    btn.setText("still alive")
    assert btn.text() == "still alive"
