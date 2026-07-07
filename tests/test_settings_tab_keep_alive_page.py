"""Tests for the Keep-Alive category page."""

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
    for f in tab.pages["features"].findChildren(InsetRow):
        if f.label_widget.text() == label:
            return f
    return None


def test_keep_alive_page_has_three_fields(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.inset_row import InsetRow
    tab = SettingsTab(settings_manager)
    fields = tab.pages["features"].findChildren(InsetRow)
    labels = {f.label_widget.text() for f in fields}
    assert {"Enable Keep-Alive", "Action", "Interval"} <= labels


def test_keep_alive_master_toggle_pre_consented(qapp, settings_manager):
    """If keep_alive_consent_acknowledged is True, toggling on writes True directly."""
    settings_manager.set("keep_alive_consent_acknowledged", True)
    from tabs.settings_tab import SettingsTab, Switch
    tab = SettingsTab(settings_manager)
    field = _field(tab, "Enable Keep-Alive")
    assert isinstance(field.control_widget, Switch)
    field.control_widget.setChecked(True)
    assert settings_manager.get("keep_alive_enabled") is True


def test_keep_alive_master_toggle_consent_decline_reverts(qapp, settings_manager, monkeypatch):
    """If consent dialog is declined, the toggle should revert to off and not persist on."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    monkeypatch.setattr(tab, "_show_keep_alive_warning_dialog", lambda: False)
    field = _field(tab, "Enable Keep-Alive")
    field.control_widget.setChecked(True)
    assert settings_manager.get("keep_alive_enabled", None) is not True
    # The control should reflect the declined state.
    assert field.control_widget.isChecked() is False


def test_keep_alive_action_changes_setting(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.pill_controls import SegmentedPill
    tab = SettingsTab(settings_manager)
    field = _field(tab, "Action")
    assert isinstance(field.control_widget, SegmentedPill)
    field.control_widget.index_changed.emit(1)  # Open / Close Book
    assert settings_manager.get("keep_alive_action") == "book"


def test_keep_alive_interval_changes_setting(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.pill_controls import SegmentedPill
    tab = SettingsTab(settings_manager)
    field = _field(tab, "Interval")
    assert isinstance(field.control_widget, SegmentedPill)
    # setCurrentIndex + emit mirrors the real click path (mousePressEvent
    # sets the index, then emits) -- get_keep_alive_delay_seconds() reads
    # the widget's own currentIndex(), not the persisted setting.
    field.control_widget.setCurrentIndex(0)  # Rapid Fire
    field.control_widget.index_changed.emit(0)
    assert settings_manager.get("keep_alive_delay") == "Rapid Fire"
    assert tab.get_keep_alive_delay_seconds() == pytest.approx(0.25)


def test_keep_alive_action_and_interval_ghosted_when_master_off(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    # Default master = False
    assert _field(tab, "Action").control_widget.isEnabled() is False
    assert _field(tab, "Interval").control_widget.isEnabled() is False


def test_highlight_keep_alive_group_switches_to_keep_alive(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab._show_category("general")
    tab.highlight_keep_alive_group()
    assert tab._current_page_key == "features"
