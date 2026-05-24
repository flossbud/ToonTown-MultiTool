"""Settings tab scroll areas use the modern auto-hide scrollbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _StubSettings:
    """Minimal settings stub; SettingsTab queries .get(key, default)."""
    def __init__(self, **kv):
        self._kv = dict(kv)
    def get(self, key, default=None):
        return self._kv.get(key, default)
    def set(self, key, value):
        self._kv[key] = value
    def on_change(self, callback):
        pass


def _scroll_areas(tab):
    return tab.findChildren(QScrollArea)


def test_settings_tab_scroll_areas_use_auto_hide_bar(qapp):
    """Every page scroll-area installed in the stack uses AutoHideScrollBar."""
    from tabs.settings_tab import SettingsTab
    from utils.widgets import AutoHideScrollBar

    tab = SettingsTab(_StubSettings(theme="dark"))
    scrolls = _scroll_areas(tab)
    # One scroll area per category (general/games/keep_alive/advanced).
    assert len(scrolls) == 4
    for sa in scrolls:
        assert isinstance(sa.verticalScrollBar(), AutoHideScrollBar)
    tab.deleteLater()


def test_settings_tab_refresh_theme_propagates_to_all_scrollbars(qapp):
    """Switching theme calls set_theme on every page's scrollbar."""
    from tabs.settings_tab import SettingsTab

    tab = SettingsTab(_StubSettings(theme="dark"))
    bars = [sa.verticalScrollBar() for sa in _scroll_areas(tab)]
    dark_qss_set = {b.styleSheet() for b in bars}
    # All bars share the same theme; expect a single QSS in dark mode.
    assert any("rgba(255, 255, 255, 0.45)" in q for q in dark_qss_set)

    tab.settings_manager.set("theme", "light")
    tab.refresh_theme()
    for b in bars:
        light_qss = b.styleSheet()
        assert "rgba(15, 23, 42, 0.30)" in light_qss
    tab.deleteLater()
