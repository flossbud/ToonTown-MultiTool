"""SettingsTab's page navigation: switching to the Features category from the
Keep-Alive links. Shell-only behaviour (the launchpad sheet has no category
pages), so these die with SettingsTab at cut-over. Moved here from
test_settings_tab_keep_alive_page.py and test_settings_consent_recorded.py
when those were retargeted to SettingsRows."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeSettingsManager:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        pass


@pytest.fixture
def settings_manager():
    return _FakeSettingsManager()


def _make_tab(qapp, sm):
    from tabs.settings_tab import SettingsTab
    return SettingsTab(sm)


def test_highlight_keep_alive_group_switches_to_keep_alive(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab._show_category("general")
    tab.highlight_keep_alive_group()
    assert tab._current_page_key == "features"


def test_show_features_category_switches_page(qapp):
    from utils.settings_keys import SETTINGS_ACTIVE_CATEGORY
    sm = _FakeSettingsManager()
    tab = _make_tab(qapp, sm)
    tab.show_features_category()
    assert tab._current_page_key == "features"
    assert sm.get(SETTINGS_ACTIVE_CATEGORY) == "features"
