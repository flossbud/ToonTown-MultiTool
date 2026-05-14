"""Tests for utils/widgets/auto_hide_scrollbar.py — modern scrollbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QScrollBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_construction_returns_qscrollbar_subclass(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    assert isinstance(bar, QScrollBar)
    bar.deleteLater()


def test_set_theme_dark_uses_white_alpha(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=True)
    qss = bar.styleSheet()

    # Width spec: bar always reserves 12px; thumb is 8px idle, 12px hover.
    assert "QScrollBar:vertical" in qss
    assert "width: 12px" in qss
    assert "min-width: 8px" in qss
    # Hover thumb expands to 12px.
    assert "QScrollBar::handle:vertical:hover" in qss
    # Dark mode: white-alpha colors.
    assert "rgba(255, 255, 255, 0.45)" in qss  # active
    assert "rgba(255, 255, 255, 0.70)" in qss  # hover
    # Track / arrows / pages all hidden.
    assert "QScrollBar::add-line:vertical" in qss
    assert "QScrollBar::sub-line:vertical" in qss
    assert "QScrollBar::add-page:vertical" in qss
    assert "QScrollBar::sub-page:vertical" in qss
    bar.deleteLater()


def test_set_theme_light_uses_dark_alpha(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=False)
    qss = bar.styleSheet()

    assert "rgba(15, 23, 42, 0.30)" in qss   # active (dark thumb on light bg)
    assert "rgba(15, 23, 42, 0.55)" in qss   # hover
    # Make sure dark-mode colors are not present.
    assert "rgba(255, 255, 255, 0.45)" not in qss
    bar.deleteLater()


def test_set_theme_is_idempotent(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=True)
    first = bar.styleSheet()
    bar.set_theme(is_dark=True)
    assert bar.styleSheet() == first
    bar.deleteLater()
