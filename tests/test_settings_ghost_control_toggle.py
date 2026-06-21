# tests/test_settings_ghost_control_toggle.py
import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def _settings_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    from tabs.settings_tab import SettingsTab
    from utils.settings_manager import SettingsManager
    return SettingsTab(settings_manager=SettingsManager())


def test_control_switch_defaults_checked(qt_app, monkeypatch, tmp_path):
    # The toggle reflects the default-ON setting on a clean config. This exercises
    # the real call-site default (get(KEY, True)) flowing into the Switch, unlike
    # asserting get(KEY, True) is True (which is tautological).
    tab = _settings_tab(monkeypatch, tmp_path)
    assert tab._ghost_control_field.control_widget.isChecked() is True


def test_control_field_greys_out_when_ghosts_off(qt_app, monkeypatch, tmp_path):
    # Fire the REAL ghost-cursors switch so this verifies the toggled.connect
    # wiring, not just the _sync_ghost_control_enabled method in isolation.
    tab = _settings_tab(monkeypatch, tmp_path)
    field = tab._ghost_control_field
    assert field.isEnabled() is True            # ghosts default ON
    tab._ghost_switch.setChecked(False)         # emits toggled(False)
    assert field.isEnabled() is False
    tab._ghost_switch.setChecked(True)          # emits toggled(True)
    assert field.isEnabled() is True
