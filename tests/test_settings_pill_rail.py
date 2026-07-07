"""Settings v2 shell - category pill rail replaces the sidebar."""
import pytest
from PySide6.QtWidgets import QApplication

from tabs.settings_tab import SettingsTab
from utils.settings_keys import SETTINGS_ACTIVE_CATEGORY


class FakeSettings:
    def __init__(self, store=None):
        self._s = dict(store or {})
    def get(self, key, default=None):
        return self._s.get(key, default)
    def set(self, key, value):
        self._s[key] = value
    def on_change(self, cb):
        pass


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_rail_replaces_sidebar(app):
    tab = SettingsTab(FakeSettings())
    assert not hasattr(tab, "sidebar")
    assert [p.key for p in tab.rail.pills] == ["general", "games", "features", "advanced"]


def test_category_click_persists_and_switches(app):
    fake = FakeSettings()
    tab = SettingsTab(fake)
    tab.rail.pills[2]._activate()
    assert fake.get(SETTINGS_ACTIVE_CATEGORY) == "features"
    assert tab._current_page_key == "features"


def test_persisted_category_restored(app):
    tab = SettingsTab(FakeSettings({SETTINGS_ACTIVE_CATEGORY: "advanced"}))
    assert tab._current_page_key == "advanced"
    assert tab.rail.active_key == "advanced"


def test_legacy_keep_alive_key_rewrites(app):
    tab = SettingsTab(FakeSettings({SETTINGS_ACTIVE_CATEGORY: "keep_alive"}))
    assert tab._current_page_key == "features"


def test_micro_label_has_no_emdash(app):
    tab = SettingsTab(FakeSettings())
    for page in tab.pages.values():
        assert "—" not in page._micro_label.text()
        assert page._micro_label.text().isupper()
