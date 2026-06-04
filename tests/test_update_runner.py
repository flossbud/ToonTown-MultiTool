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


_FLATPAK_ASSET = {
    "name": "TTMultiTool-v2.4.0-Linux-x86_64.flatpak",
    "browser_download_url": "https://x/bundle",
    "size": 1,
}


def test_runner_dispatches_flatpak_downloads_and_installs(monkeypatch):
    # A bundle-distributed Flatpak has no live remote, so `flatpak update`
    # no-ops. The handler must instead download the .flatpak asset and reinstall
    # it (the same download-and-install shape the .deb/.exe handlers use).
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: False)
    monkeypatch.setattr("utils.update_runner.flatpak_install_scope", lambda: "--system")
    monkeypatch.setattr(runner, "_download_asset",
                        lambda asset, out_dir=None: "/tmp/TTMultiTool.flatpak")
    spawned = []
    monkeypatch.setattr(
        "utils.update_runner.run_in_terminal",
        lambda cmd, on_exit: spawned.append(cmd) or True,
    )
    runner.run_update({"tag_name": "v2.4.0-a", "html_url": "https://example/r",
                       "assets": [_FLATPAK_ASSET]})
    assert spawned == [["flatpak", "install", "--system", "--reinstall", "-y",
                        "/tmp/TTMultiTool.flatpak"]]


def test_flatpak_no_asset_opens_release(monkeypatch):
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    runner.run_update({"html_url": "https://example/release",
                       "assets": [{"name": "irrelevant.zip"}]})
    assert opened == ["https://example/release"]


def test_flatpak_stages_to_host_visible_dir_in_sandbox(monkeypatch):
    # Inside the sandbox the bundle must be downloaded to a host-visible path,
    # because the `flatpak install` runs as a host process that cannot see the
    # sandbox's private /tmp.
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)
    monkeypatch.setattr("utils.host_spawn.host_visible_cache_dir",
                        lambda name: "/host/cache/" + name)
    captured = {}
    def fake_download(asset, out_dir=None):
        captured["out_dir"] = out_dir
        return "/host/cache/update/x.flatpak"
    monkeypatch.setattr(runner, "_download_asset", fake_download)
    monkeypatch.setattr("utils.update_runner.run_in_terminal", lambda cmd, on_exit: True)
    runner.run_update({"assets": [_FLATPAK_ASSET]})
    assert captured["out_dir"] == "/host/cache/update"


def test_flatpak_payload_not_prewrapped_in_sandbox(monkeypatch):
    # Regression guard for the double-wrap hazard: even inside the sandbox the
    # command handed to the terminal launcher must stay raw. run_in_terminal
    # applies the flatpak-spawn --host wrap once around the whole terminal argv.
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.FLATPAK)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)
    monkeypatch.setattr("utils.host_spawn.host_visible_cache_dir",
                        lambda name: "/host/cache/" + name)
    monkeypatch.setattr("utils.update_runner.flatpak_install_scope", lambda: "--system")
    monkeypatch.setattr(runner, "_download_asset",
                        lambda asset, out_dir=None: "/host/cache/update/b.flatpak")
    spawned = []
    monkeypatch.setattr(
        "utils.update_runner.run_in_terminal",
        lambda cmd, on_exit: spawned.append(cmd) or True,
    )
    runner.run_update({"assets": [_FLATPAK_ASSET]})
    assert spawned == [["flatpak", "install", "--system", "--reinstall", "-y",
                        "/host/cache/update/b.flatpak"]]
    assert "flatpak-spawn" not in spawned[0]


def test_flatpak_install_scope_detects_user(tmp_path):
    from utils.update_runner import flatpak_install_scope
    info = tmp_path / "flatpak-info"
    info.write_text(
        "[Instance]\napp-path=/home/u/.local/share/flatpak/app/io.x/x86_64/master/abc/files\n"
    )
    assert flatpak_install_scope(str(info)) == "--user"


def test_flatpak_install_scope_detects_system(tmp_path):
    from utils.update_runner import flatpak_install_scope
    info = tmp_path / "flatpak-info"
    info.write_text(
        "[Instance]\napp-path=/var/lib/flatpak/app/io.x/x86_64/master/abc/files\n"
    )
    assert flatpak_install_scope(str(info)) == "--system"


def test_flatpak_install_scope_defaults_system_when_missing(tmp_path):
    from utils.update_runner import flatpak_install_scope
    assert flatpak_install_scope(str(tmp_path / "nope")) == "--system"


def test_restart_app_flatpak_relaunches_via_flatpak_run_not_execv(monkeypatch):
    # os.execv would re-run the OLD sandbox; under Flatpak the restart must
    # launch a fresh `flatpak run` on the host and quit instead.
    import os as _os
    parent = MagicMock()
    runner = UpdateRunner(parent)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)
    popened = []
    monkeypatch.setattr("utils.host_spawn.host_popen", lambda argv, **kw: popened.append(argv))
    execv_called = []
    monkeypatch.setattr(_os, "execv", lambda *a: execv_called.append(a))
    quit_called = []
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda *a: quit_called.append(True)))
    runner._restart_app()
    assert popened == [["flatpak", "run", "io.github.flossbud.ToonTownMultiTool"]]
    assert execv_called == []
    assert quit_called == [True]
