"""Settings tab uses the modern auto-hide scrollbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


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


def test_settings_tab_scroll_area_uses_auto_hide_bar(qapp):
    from tabs.settings_tab import SettingsTab
    from utils.widgets import AutoHideScrollBar

    tab = SettingsTab(_StubSettings(theme="dark"))
    assert isinstance(tab._scroll.verticalScrollBar(), AutoHideScrollBar)
    tab.deleteLater()


def test_settings_tab_refresh_theme_propagates_to_scrollbar(qapp):
    """Switching theme should re-call set_theme on the bar so the QSS swaps."""
    from tabs.settings_tab import SettingsTab

    tab = SettingsTab(_StubSettings(theme="dark"))
    bar = tab._scroll.verticalScrollBar()
    dark_qss = bar.styleSheet()
    assert "rgba(255, 255, 255, 0.45)" in dark_qss

    tab.settings_manager.set("theme", "light")
    tab.refresh_theme()
    light_qss = bar.styleSheet()
    assert "rgba(15, 23, 42, 0.30)" in light_qss
    assert dark_qss != light_qss
    tab.deleteLater()
