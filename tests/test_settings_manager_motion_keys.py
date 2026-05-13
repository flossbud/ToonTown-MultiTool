"""Verify the two new motion-related settings keys are wired with
explicit defaults in SettingsManager."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.settings_manager import SettingsManager


def test_reduce_motion_default_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sm = SettingsManager()
    assert sm.get("reduce_motion") is False


def test_reduce_motion_set_explicitly_default_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sm = SettingsManager()
    assert sm.get("reduce_motion_set_explicitly") is False


def test_setting_reduce_motion_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sm = SettingsManager()
    sm.set("reduce_motion", True)
    sm.set("reduce_motion_set_explicitly", True)

    sm2 = SettingsManager()
    assert sm2.get("reduce_motion") is True
    assert sm2.get("reduce_motion_set_explicitly") is True
