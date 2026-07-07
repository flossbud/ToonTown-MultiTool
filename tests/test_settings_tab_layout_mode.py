"""Settings tab participation in the app-wide compact<->full layout mode."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


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
    """At a maximized-like width the page sits centered in the content
    column, not glued to the left edge. The pill rail sits above the
    content, so horizontally the page centers in the full tab width."""
    from PySide6.QtCore import QPoint
    from tabs.settings_tab import SettingsTab, SETTINGS_CONTENT_MAX_W
    tab = SettingsTab(settings_manager)
    tab.resize(2000, 900)
    tab.show()
    QApplication.processEvents()
    page = tab.pages["general"]
    assert page.width() == SETTINGS_CONTENT_MAX_W
    x = page.mapTo(tab, QPoint(0, 0)).x()
    expected = (2000 - SETTINGS_CONTENT_MAX_W) // 2
    assert abs(x - expected) <= 30  # scrollbar gutter tolerance
    tab.hide()


def test_set_layout_mode_stores_mode_without_reshaping_shell(qapp, settings_manager):
    """The v2 shell is identical in both modes: set_layout_mode just records
    the mode (contract kept for main.py); the pill rail stays mounted and the
    content column stays width-capped."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert tab._layout_mode == "compact"  # constructs compact
    tab.set_layout_mode("full")
    assert tab._layout_mode == "full"
    assert tab.rail is not None
    tab.set_layout_mode("compact")
    assert tab._layout_mode == "compact"
    assert tab.rail is not None


def test_set_layout_mode_ignores_unknown_modes(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.set_layout_mode("full")
    tab.set_layout_mode("banana")
    assert tab._layout_mode == "full"


def test_set_layout_mode_reapply_keeps_mode(qapp, settings_manager):
    """Re-applying the current mode is harmless: the v2 shell has no per-mode
    reshaping to short-circuit."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.set_layout_mode("full")
    tab.set_layout_mode("full")
    assert tab._layout_mode == "full"
    tab.set_layout_mode("compact")
    tab.set_layout_mode("compact")
    assert tab._layout_mode == "compact"
