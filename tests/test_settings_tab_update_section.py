"""Tests for the Updates panel on the General settings page."""

import pytest
from PySide6.QtWidgets import QApplication

from utils.settings_manager import SettingsManager
from tabs.settings_tab import SettingsTab, Switch
from utils.widgets.inset_row import InsetRow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _find_field(tab, label_text):
    for f in tab.pages["general"].findChildren(InsetRow):
        if f.label_widget.text() == label_text:
            return f
    return None


def test_updates_section_has_toggle_and_check_button(qapp, monkeypatch, tmp_path):
    """The Updates panel exposes a Switch for 'on startup' and a 'Check now' button."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("utils.build_flavor.config_dir_name", lambda: "ttmt_test")
    sm = SettingsManager()
    sm.set("check_for_updates_at_startup", True)
    tab = SettingsTab(sm)
    toggle_field = _find_field(tab, "Check for updates on startup")
    assert toggle_field is not None
    assert isinstance(toggle_field.control_widget, Switch)
    assert toggle_field.control_widget.isChecked() is True
    # 'Check now' button hung off the second Updates field
    check_now_field = _find_field(tab, "Check for updates now")
    assert check_now_field is not None
    assert tab._check_now_btn is not None
    assert tab._check_now_btn.text() == "Check now"


def test_updates_toggle_writes_setting(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("utils.build_flavor.config_dir_name", lambda: "ttmt_test")
    sm = SettingsManager()
    sm.set("check_for_updates_at_startup", False)
    tab = SettingsTab(sm)
    toggle_field = _find_field(tab, "Check for updates on startup")
    assert toggle_field is not None
    # Switch.setChecked(<different>) emits toggled, which writes the setting.
    toggle_field.control_widget.setChecked(True)
    assert sm.get("check_for_updates_at_startup") is True
