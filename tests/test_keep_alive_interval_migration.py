"""Keep-Alive interval: '10 min' removed + persisted values migrate to '5 min'."""
import pytest
from PySide6.QtWidgets import QApplication

from tabs.settings_tab import SettingsTab


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


def test_ten_min_option_gone(app):
    tab = SettingsTab(FakeSettings())
    assert "10 min" not in tab._ka_delay_options
    assert tab._ka_delay_options[-1] == "5 min"


def test_persisted_ten_min_migrates(app):
    fake = FakeSettings({"keep_alive_delay": "10 min"})
    tab = SettingsTab(fake)
    assert fake.get("keep_alive_delay") == "5 min"
    assert tab.get_keep_alive_delay_seconds() == 300


def test_gating_disables_rows(app):
    tab = SettingsTab(FakeSettings())
    tab._refresh_keep_alive_enabled_state(False)
    assert not tab._ka_action_row.isEnabled()
    assert not tab._ka_delay_row.isEnabled()
    tab._refresh_keep_alive_enabled_state(True)
    assert tab._ka_action_row.isEnabled()
