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


def test_control_cards_setting_defaults_true():
    from utils.settings_keys import GHOST_CURSORS_CONTROL_CARDS
    from utils.settings_manager import SettingsManager
    import tempfile, os
    d = tempfile.mkdtemp()
    os.environ["TTMT_CONFIG_DIR"] = d
    sm = SettingsManager()
    assert sm.get(GHOST_CURSORS_CONTROL_CARDS, True) is True


def test_control_field_greys_out_when_ghosts_off(qt_app, monkeypatch, tmp_path):
    from utils.settings_keys import GHOST_CURSORS_ENABLED
    tab = _settings_tab(monkeypatch, tmp_path)
    # The field exists and tracks the ghost-cursors switch.
    field = tab._ghost_control_field
    tab.settings_manager.set(GHOST_CURSORS_ENABLED, False)
    tab._sync_ghost_control_enabled(False)
    assert field.isEnabled() is False
    tab._sync_ghost_control_enabled(True)
    assert field.isEnabled() is True
