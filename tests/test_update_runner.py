from unittest.mock import MagicMock

import pytest

from utils.install_method import InstallMethod
from utils.update_runner import (
    pick_asset,
    aur_package_name,
    flatpak_app_id,
    find_aur_helper,
    UpdateRunner,
)


def test_pick_asset_finds_windows_exe():
    assets = [
        {"name": "ToonTownMultiTool-Setup-v2.4.0-Windows-x86_64.exe", "browser_download_url": "https://x/a.exe", "size": 100},
        {"name": "TTMultiTool-v2.4.0-Linux-x86_64.AppImage", "browser_download_url": "https://x/b.AppImage", "size": 200},
    ]
    chosen = pick_asset(assets, suffix=".exe")
    assert chosen["name"].endswith(".exe")


def test_pick_asset_returns_none_when_missing():
    assets = [{"name": "TTMultiTool-v2.4.0.flatpak", "browser_download_url": "https://x/c", "size": 1}]
    assert pick_asset(assets, suffix=".exe") is None


def test_aur_package_name_stable():
    assert aur_package_name(is_beta=False) == "ttmt"


def test_aur_package_name_beta():
    assert aur_package_name(is_beta=True) == "ttmt-beta"


def test_flatpak_app_id_is_constant():
    assert flatpak_app_id() == "io.github.flossbud.ToonTownMultiTool"


def test_find_aur_helper_prefers_paru(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("paru", "yay") else None)
    assert find_aur_helper() == "/usr/bin/paru"


def test_find_aur_helper_returns_none_when_no_helper(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_aur_helper() is None


def test_runner_dispatches_appimage_to_browser(monkeypatch):
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.APPIMAGE)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    runner.run_update({"tag_name": "v2.4.0-a", "html_url": "https://example/release", "assets": []})
    assert opened == ["https://example/release"]


def test_runner_dispatches_aur_to_terminal(monkeypatch):
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.AUR)
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/paru" if name == "paru" else None)
    spawned = []
    def fake_run_in_terminal(cmd, on_exit):
        spawned.append(cmd)
        return True
    monkeypatch.setattr("utils.update_runner.run_in_terminal", fake_run_in_terminal)
    runner.run_update({"tag_name": "v2.4.0-a", "html_url": "https://example/r", "assets": []})
    assert spawned and "paru" in spawned[0][0]
    assert "ttmt-beta" in spawned[0]


def test_runner_dispatches_flatpak_to_terminal(monkeypatch):
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    spawned = []
    monkeypatch.setattr(
        "utils.update_runner.run_in_terminal",
        lambda cmd, on_exit: spawned.append(cmd) or True,
    )
    runner.run_update({"tag_name": "v2.4.0-a", "html_url": "https://example/r", "assets": []})
    assert spawned == [["flatpak", "update", "-y", "io.github.flossbud.ToonTownMultiTool"]]


def test_flatpak_payload_not_prewrapped_in_sandbox(monkeypatch):
    # Regression guard for the double-wrap hazard: even when running inside the
    # sandbox (in_flatpak True), the command handed to the terminal launcher
    # must stay raw. The flatpak-spawn --host wrap is applied once, by the
    # terminal launcher around the whole terminal argv -- never pre-applied to
    # the payload here (a host terminal cannot itself invoke flatpak-spawn).
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)
    spawned = []
    monkeypatch.setattr(
        "utils.update_runner.run_in_terminal",
        lambda cmd, on_exit: spawned.append(cmd) or True,
    )
    runner.run_update({"tag_name": "v2.4.0-a", "html_url": "https://example/r", "assets": []})
    assert spawned == [["flatpak", "update", "-y", "io.github.flossbud.ToonTownMultiTool"]]
    assert "flatpak-spawn" not in spawned[0]
