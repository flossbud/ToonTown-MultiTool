import os
# Must be set BEFORE importing main / app modules.
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import types
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen", reason="offscreen only"
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_key_constant_value_and_default(isolated_config):
    from utils.settings_keys import START_IN_FLOAT_UI_MODE
    from utils.settings_manager import SettingsManager
    assert START_IN_FLOAT_UI_MODE == "start_in_float_ui_mode"
    m = SettingsManager()
    assert m.get(START_IN_FLOAT_UI_MODE, False) is False   # default OFF


def test_key_round_trips_across_instances(isolated_config):
    from utils.settings_keys import START_IN_FLOAT_UI_MODE
    from utils.settings_manager import SettingsManager
    m1 = SettingsManager()
    m1.set(START_IN_FLOAT_UI_MODE, True)
    m2 = SettingsManager()
    assert m2.get(START_IN_FLOAT_UI_MODE, False) is True
