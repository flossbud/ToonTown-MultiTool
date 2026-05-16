# tests/test_update_settings_defaults.py
import json
from unittest.mock import patch

import pytest

from utils.install_method import InstallMethod
from utils.settings_manager import SettingsManager


def _make_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Stub config_dir name so we don't depend on beta/stable in this test
    monkeypatch.setattr(
        "utils.build_flavor.config_dir_name",
        lambda: "ttmt_test",
    )
    return SettingsManager()


def test_windows_path_is_noop_when_key_present(tmp_path, monkeypatch):
    # Simulate installer having already written the key
    cfg = tmp_path / "ttmt_test"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"check_for_updates_at_startup": False}))
    monkeypatch.setattr(
        "utils.install_method.detect",
        lambda: InstallMethod.WINDOWS_INSTALLER,
    )
    sm = _make_manager(tmp_path, monkeypatch)
    from utils.update_defaults import apply_first_launch_defaults
    apply_first_launch_defaults(sm)
    # Setting must not have been overwritten.
    assert sm.get("check_for_updates_at_startup") is False


@pytest.mark.parametrize("method,expected", [
    (InstallMethod.APPIMAGE, True),
    (InstallMethod.SOURCE, True),
    (InstallMethod.FLATPAK, False),
    (InstallMethod.AUR, False),
    (InstallMethod.DEB, False),
])
def test_linux_first_launch_default(method, expected, tmp_path, monkeypatch):
    monkeypatch.setattr("utils.install_method.detect", lambda: method)
    sm = _make_manager(tmp_path, monkeypatch)
    # Key must be absent initially.
    assert sm.get("check_for_updates_at_startup") is None or "check_for_updates_at_startup" not in sm.settings
    from utils.update_defaults import apply_first_launch_defaults
    apply_first_launch_defaults(sm)
    assert sm.get("check_for_updates_at_startup") is expected


def test_does_not_overwrite_existing_key(tmp_path, monkeypatch):
    cfg = tmp_path / "ttmt_test"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"check_for_updates_at_startup": True}))
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    sm = _make_manager(tmp_path, monkeypatch)
    from utils.update_defaults import apply_first_launch_defaults
    apply_first_launch_defaults(sm)
    # User's saved value (True) preserved even though Flatpak default is False.
    assert sm.get("check_for_updates_at_startup") is True
