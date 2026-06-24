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


class _FakeSettings:
    def __init__(self, store): self._store = dict(store)
    def get(self, key, default=None): return self._store.get(key, default)
    def set(self, key, value): self._store[key] = value


class _FakeBackend:
    def __init__(self, available): self._available = available
    def is_available(self): return self._available


class _FakeController:
    def __init__(self, active=False, enter_returns=True):
        self._active = active
        self._enter_returns = enter_returns
        self.enter_calls = 0
    @property
    def is_active(self): return self._active
    def enter(self):
        self.enter_calls += 1
        return self._enter_returns


def _make_stub(enabled, available, active):
    return types.SimpleNamespace(
        settings_manager=_FakeSettings({"start_in_float_ui_mode": enabled}),
        _overlay_backend=_FakeBackend(available),
        _mode_controller=_FakeController(active=active),
    )


def test_hook_enters_when_enabled_available_and_inactive():
    from main import MultiToonTool
    stub = _make_stub(enabled=True, available=True, active=False)
    assert MultiToonTool._maybe_enter_float_mode_at_startup(stub) is True
    assert stub._mode_controller.enter_calls == 1


def test_hook_noop_when_disabled():
    from main import MultiToonTool
    stub = _make_stub(enabled=False, available=True, active=False)
    assert MultiToonTool._maybe_enter_float_mode_at_startup(stub) is False
    assert stub._mode_controller.enter_calls == 0


def test_hook_noop_when_backend_unavailable():
    from main import MultiToonTool
    stub = _make_stub(enabled=True, available=False, active=False)
    assert MultiToonTool._maybe_enter_float_mode_at_startup(stub) is False
    assert stub._mode_controller.enter_calls == 0


def test_hook_noop_when_already_active():
    from main import MultiToonTool
    stub = _make_stub(enabled=True, available=True, active=True)
    assert MultiToonTool._maybe_enter_float_mode_at_startup(stub) is False
    assert stub._mode_controller.enter_calls == 0


def _patch_backend(monkeypatch, available):
    import utils.overlay.backend as backend_mod
    class _StubBackend:
        def is_available(self): return available
    monkeypatch.setattr(backend_mod, "get_overlay_backend", lambda: _StubBackend())


def _build_settings_tab(isolated_config):
    from PySide6.QtWidgets import QWidget
    from tabs.settings_tab import SettingsTab
    from utils.settings_manager import SettingsManager
    tab = SettingsTab(SettingsManager())
    sw = tab.findChild(QWidget, "start_in_float_ui_switch")
    return tab, sw


def test_settings_switch_present_and_reflects_stored_value(isolated_config, monkeypatch):
    _app()
    _patch_backend(monkeypatch, available=True)
    from utils.settings_keys import START_IN_FLOAT_UI_MODE
    from utils.settings_manager import SettingsManager
    SettingsManager().set(START_IN_FLOAT_UI_MODE, True)   # pre-store ON
    tab, sw = _build_settings_tab(isolated_config)
    assert sw is not None, "Start in Float UI switch missing from General page"
    assert sw.isEnabled() is True
    assert sw.isChecked() is True


def test_settings_switch_defaults_unchecked_when_unset(isolated_config, monkeypatch):
    _app()
    _patch_backend(monkeypatch, available=True)
    tab, sw = _build_settings_tab(isolated_config)
    assert sw is not None
    assert sw.isChecked() is False


def test_settings_switch_disabled_when_backend_unavailable(isolated_config, monkeypatch):
    _app()
    _patch_backend(monkeypatch, available=False)
    tab, sw = _build_settings_tab(isolated_config)
    assert sw is not None
    assert sw.isEnabled() is False
    assert "Shape extension" in sw.toolTip()
