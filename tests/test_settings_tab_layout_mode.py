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


@pytest.fixture
def settings_manager():
    class _Stub:
        def __init__(self):
            self._d = {"theme": "dark"}
            self._listeners = []

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
            for fn in list(self._listeners):
                fn(key, value)

        def on_change(self, fn):
            self._listeners.append(fn)

    return _Stub()


def test_every_page_is_width_capped(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, SETTINGS_CONTENT_MAX_W
    tab = SettingsTab(settings_manager)
    for key, page in tab.pages.items():
        assert page.maximumWidth() == SETTINGS_CONTENT_MAX_W, key


def test_every_scroll_area_centers_its_page(qapp, settings_manager):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    scrolls = [
        tab._stack.widget(i)
        for i in range(tab._stack.count())
    ]
    assert scrolls and all(isinstance(s, QScrollArea) for s in scrolls)
    for s in scrolls:
        assert s.alignment() & Qt.AlignHCenter
        assert s.alignment() & Qt.AlignTop


def test_wide_tab_centers_content_column(qapp, settings_manager):
    """At a maximized-like width the page sits centered between the rail
    and the right edge, not glued to the rail."""
    from PySide6.QtCore import QPoint
    from tabs.settings_tab import SettingsTab, SETTINGS_CONTENT_MAX_W
    tab = SettingsTab(settings_manager)
    tab.resize(2000, 900)
    tab.show()
    QApplication.processEvents()
    page = tab.pages["general"]
    assert page.width() == SETTINGS_CONTENT_MAX_W
    x = page.mapTo(tab, QPoint(0, 0)).x()
    rail_w = tab.sidebar.width()
    expected = rail_w + (2000 - rail_w - SETTINGS_CONTENT_MAX_W) // 2
    assert abs(x - expected) <= 30  # scrollbar gutter tolerance
    tab.hide()


def test_set_layout_mode_drives_sidebar_expansion(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert tab.sidebar.width() == 130  # constructs compact
    tab.set_layout_mode("full")
    assert tab.sidebar.width() == 200
    tab.set_layout_mode("compact")
    assert tab.sidebar.width() == 130


def test_set_layout_mode_ignores_unknown_modes(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.set_layout_mode("full")
    tab.set_layout_mode("banana")
    assert tab.sidebar.width() == 200


def test_set_layout_mode_is_idempotent(qapp, settings_manager):
    """Re-applying the current mode must short-circuit at the tab level,
    not just rely on Sidebar.set_expanded's own no-op guard."""
    from unittest.mock import patch
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.set_layout_mode("full")
    with patch.object(tab.sidebar, "set_expanded") as spy:
        tab.set_layout_mode("full")
        spy.assert_not_called()
    assert tab.sidebar.width() == 200
    tab.set_layout_mode("compact")
    with patch.object(tab.sidebar, "set_expanded") as spy:
        tab.set_layout_mode("compact")
        spy.assert_not_called()
    assert tab.sidebar.width() == 130
