"""Tests for the keep-alive opt-in master toggle (TTR/CC TOS compliance)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_keep_alive_master_default_off(tmp_path, monkeypatch):
    """A fresh SettingsManager has keep_alive_enabled defaulting to False."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("keep_alive_enabled") is False
