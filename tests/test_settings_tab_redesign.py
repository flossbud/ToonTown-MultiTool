"""Tests for the Settings tab redesign (2026-05-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_advanced_collapsed_defaults_true(tmp_path, monkeypatch):
    """advanced_collapsed defaults to True on a fresh SettingsManager."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("advanced_collapsed") is True
