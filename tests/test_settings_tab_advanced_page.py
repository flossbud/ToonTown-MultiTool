"""Tests for the Advanced category page."""

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
            self._d = {}
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


def _field(tab, label):
    from utils.widgets.inset_row import InsetRow
    for f in tab.pages["advanced"].findChildren(InsetRow):
        if f.label_widget.text() == label:
            return f
    return None


def test_advanced_has_logging_input_backend_clear_credentials(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.inset_row import InsetRow
    tab = SettingsTab(settings_manager)
    labels = {f.label_widget.text() for f in tab.pages["advanced"].findChildren(InsetRow)}
    assert {"Enable Logging", "Input Backend", "Clear Stored Credentials"} <= labels


def test_advanced_logging_toggle_persists_and_emits(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, Switch
    tab = SettingsTab(settings_manager)
    received = []
    tab.debug_visibility_changed.connect(received.append)
    field = _field(tab, "Enable Logging")
    assert isinstance(field.control_widget, Switch)
    field.control_widget.setChecked(True)
    assert settings_manager.get("show_debug_tab") is True
    assert received == [True]


def test_advanced_clear_credentials_emits_signal(qapp, settings_manager, monkeypatch):
    from tabs.settings_tab import SettingsTab
    from PySide6.QtWidgets import QMessageBox
    tab = SettingsTab(settings_manager)
    # Bypass the modal — answer "Yes".
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    received = []
    tab.clear_credentials_requested.connect(lambda: received.append(True))
    field = _field(tab, "Clear Stored Credentials")
    field.control_widget.click()
    assert received == [True]
