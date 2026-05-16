import pytest
from PySide6.QtWidgets import QApplication

from utils.settings_manager import SettingsManager
from tabs.settings_tab import SettingsTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_updates_section_has_toggle_and_button(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("utils.build_flavor.config_dir_name", lambda: "ttmt_test")
    sm = SettingsManager()
    sm.set("check_for_updates_at_startup", True)
    tab = SettingsTab(sm)
    assert hasattr(tab, "update_check_toggle")
    assert hasattr(tab, "update_check_now_btn")
    assert tab.update_check_toggle.isChecked() is True


def test_updates_toggle_writes_setting(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("utils.build_flavor.config_dir_name", lambda: "ttmt_test")
    sm = SettingsManager()
    sm.set("check_for_updates_at_startup", False)
    tab = SettingsTab(sm)
    # Emit the ToggleRow's toggled(bool) signal directly — the production
    # path is identical: IOSToggle → ToggleRow.toggled → _on_check_for_updates_toggled.
    tab.update_check_toggle.toggled.emit(True)
    assert sm.get("check_for_updates_at_startup") is True
