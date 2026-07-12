"""The Settings Keep-Alive master toggle must RECORD consent when the user
accepts the ToS dialog. Today keep_alive_consent_acknowledged is read but
never written by the app (only the installer merge sets it), so the warning
dialog reappears on every off-to-on flip. The popover (new feature-discovery
surface) shares the same consent key, so consent must be asked once across
both surfaces."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettingsManager:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        pass


def _make_tab(qapp, sm):
    from tabs.settings_tab import SettingsTab
    return SettingsTab(sm)


def test_dialog_accept_records_consent(qapp, monkeypatch):
    sm = _FakeSettingsManager()
    tab = _make_tab(qapp, sm)
    monkeypatch.setattr(tab, "_show_keep_alive_warning_dialog", lambda: True)
    tab._on_keep_alive_master_toggle(True)
    assert sm.get("keep_alive_enabled") is True
    assert sm.get("keep_alive_consent_acknowledged") is True


def test_dialog_cancel_records_nothing(qapp, monkeypatch):
    sm = _FakeSettingsManager()
    tab = _make_tab(qapp, sm)
    monkeypatch.setattr(tab, "_show_keep_alive_warning_dialog", lambda: False)
    tab._on_keep_alive_master_toggle(True)
    assert sm.get("keep_alive_enabled") is None
    assert sm.get("keep_alive_consent_acknowledged") is None


def test_already_acknowledged_skips_dialog(qapp, monkeypatch):
    sm = _FakeSettingsManager({"keep_alive_consent_acknowledged": True})
    tab = _make_tab(qapp, sm)
    called = []
    monkeypatch.setattr(
        tab, "_show_keep_alive_warning_dialog",
        lambda: called.append(True) or True,
    )
    tab._on_keep_alive_master_toggle(True)
    assert called == []
    assert sm.get("keep_alive_enabled") is True


def test_show_features_category_switches_page(qapp):
    from utils.settings_keys import SETTINGS_ACTIVE_CATEGORY
    sm = _FakeSettingsManager()
    tab = _make_tab(qapp, sm)
    tab.show_features_category()
    assert tab._current_page_key == "features"
    assert sm.get(SETTINGS_ACTIVE_CATEGORY) == "features"
