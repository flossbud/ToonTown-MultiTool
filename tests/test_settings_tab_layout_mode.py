"""Settings tab participation in the app-wide compact<->full layout mode."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


CATEGORIES = [
    ("general", "General"),
    ("games", "Games"),
    ("features", "Features"),
    ("advanced", "Advanced"),
]


def test_sidebar_expands_to_full_metrics(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    sb.set_expanded(True)
    assert sb.width() == 200
    assert all(item.height() == 44 for item in sb.items)


def test_sidebar_collapses_back_to_compact_metrics(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    sb.set_expanded(True)
    sb.set_expanded(False)
    assert sb.width() == 130
    assert all(item.height() == 36 for item in sb.items)


def test_sidebar_expanded_label_font_grows(qapp):
    from tabs.settings_tab import Sidebar
    from utils.theme_manager import get_theme_colors
    sb = Sidebar(CATEGORIES)
    sb.apply_theme(get_theme_colors(True), True)
    assert "12.5px" in sb.items[0].label_widget.styleSheet()
    sb.set_expanded(True)
    assert "14px" in sb.items[0].label_widget.styleSheet()


def test_sidebar_expanded_sizing_survives_theme_refresh(qapp):
    """Regression: apply_theme after expansion must keep the expanded font,
    since _apply_styles rebuilds the label stylesheet."""
    from tabs.settings_tab import Sidebar
    from utils.theme_manager import get_theme_colors
    sb = Sidebar(CATEGORIES)
    sb.set_expanded(True)
    sb.apply_theme(get_theme_colors(True), True)
    assert sb.width() == 200
    assert "14px" in sb.items[0].label_widget.styleSheet()
