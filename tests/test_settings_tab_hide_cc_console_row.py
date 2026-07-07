"""Tests for the 'Hide CC launch console' field in Settings > Games."""

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


def _find_field(tab, label_text):
    """Find an InsetRow on the Games page (v2 kit) by its label text."""
    from utils.widgets.inset_row import InsetRow
    for f in tab.pages["games"].findChildren(InsetRow):
        if f.label_widget.text() == label_text:
            return f
    return None


def test_hide_cc_console_field_exists_and_defaults_on(qapp):
    """Defaults to ON when the key is missing from settings."""
    from tabs import settings_tab
    settings = _SettingsStub({})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    field = _find_field(tab, "Hide CC launch console")
    assert field is not None
    assert field.control_widget.isChecked() is True


def test_hide_cc_console_field_reflects_stored_off(qapp):
    from tabs import settings_tab
    from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE
    settings = _SettingsStub({CC_HIDE_LAUNCH_CONSOLE: False})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    field = _find_field(tab, "Hide CC launch console")
    assert field is not None
    assert field.control_widget.isChecked() is False


def test_hide_cc_console_field_toggling_writes_setting(qapp):
    from tabs import settings_tab
    from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE
    settings = _SettingsStub({})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    field = _find_field(tab, "Hide CC launch console")
    assert field is not None
    # Switch.setChecked(<different>) emits toggled, which writes the setting.
    field.control_widget.setChecked(False)
    assert settings.get(CC_HIDE_LAUNCH_CONSOLE) is False
    field.control_widget.setChecked(True)
    assert settings.get(CC_HIDE_LAUNCH_CONSOLE) is True
