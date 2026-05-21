"""Tests for the 'Hide CC launch console' ToggleRow in Settings > Games."""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _SettingsStub:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, key, default=None):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value
    def on_change(self, callback):
        pass


def test_hide_cc_console_row_exists_and_defaults_on(qapp, monkeypatch):
    """Defaults to ON when the key is missing from settings."""
    from tabs import settings_tab
    monkeypatch.setattr(settings_tab, "discover_cc_installs", lambda: [])
    settings = _SettingsStub({})  # no key stored
    tab = settings_tab.SettingsTab(settings_manager=settings)
    row = getattr(tab, "hide_cc_console_row", None)
    assert row is not None, "expected SettingsTab to expose hide_cc_console_row"
    # ToggleRow has a .toggle attribute (IOSToggle) with isChecked().
    assert row.toggle.isChecked() is True


def test_hide_cc_console_row_reflects_stored_off(qapp, monkeypatch):
    from tabs import settings_tab
    from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE
    monkeypatch.setattr(settings_tab, "discover_cc_installs", lambda: [])
    settings = _SettingsStub({CC_HIDE_LAUNCH_CONSOLE: False})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab.hide_cc_console_row.toggle.isChecked() is False


def test_hide_cc_console_row_toggling_writes_setting(qapp, monkeypatch):
    from tabs import settings_tab
    from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE
    monkeypatch.setattr(settings_tab, "discover_cc_installs", lambda: [])
    settings = _SettingsStub({})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    # Simulate a user toggle to OFF.
    tab.hide_cc_console_row.toggled.emit(False)
    assert settings.get(CC_HIDE_LAUNCH_CONSOLE) is False
    tab.hide_cc_console_row.toggled.emit(True)
    assert settings.get(CC_HIDE_LAUNCH_CONSOLE) is True
