import os
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


def test_use_system_title_bar_defaults_false(tmp_path, monkeypatch):
    # Point config at a tmp dir so the real settings.json is never touched.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "cfg"))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("use_system_title_bar") is False
