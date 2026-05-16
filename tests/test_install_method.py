import sys
from unittest.mock import patch, MagicMock

import pytest

from utils.install_method import InstallMethod, detect, _reset_cache_for_tests


@pytest.fixture(autouse=True)
def _reset():
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


def test_windows_installer_when_frozen_on_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert detect() == InstallMethod.WINDOWS_INSTALLER


def test_appimage_via_env(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", "/tmp/TTMT.AppImage")
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    assert detect() == InstallMethod.APPIMAGE


def test_flatpak_via_env(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("FLATPAK_ID", "io.github.flossbud.ToonTownMultiTool")
    assert detect() == InstallMethod.FLATPAK


def test_flatpak_via_marker_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    marker = tmp_path / "flatpak-info"
    marker.write_text("")
    monkeypatch.setattr(
        "utils.install_method._FLATPAK_MARKER", str(marker)
    )
    assert detect() == InstallMethod.FLATPAK


def test_aur_when_arch_and_pacman_owns(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    arch_marker = tmp_path / "arch-release"
    arch_marker.write_text("")
    monkeypatch.setattr(
        "utils.install_method._ARCH_MARKER", str(arch_marker)
    )

    def fake_run(cmd, *a, **kw):
        from subprocess import CompletedProcess
        if cmd[:2] == ["pacman", "-Qo"]:
            return CompletedProcess(cmd, 0, stdout="/usr/bin/ttmt is owned by ttmt-beta 2.3.0\n", stderr="")
        return CompletedProcess(cmd, 1, stdout="", stderr="not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert detect() == InstallMethod.AUR


def test_deb_when_dpkg_owns(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(
        "utils.install_method._ARCH_MARKER", "/nonexistent"
    )

    def fake_run(cmd, *a, **kw):
        from subprocess import CompletedProcess
        if cmd[:2] == ["dpkg", "-S"]:
            return CompletedProcess(cmd, 0, stdout="toontown-multitool: /usr/bin/ttmt\n", stderr="")
        return CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert detect() == InstallMethod.DEB


def test_source_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr("utils.install_method._FLATPAK_MARKER", "/nonexistent")
    monkeypatch.setattr("utils.install_method._ARCH_MARKER", "/nonexistent")

    def fake_run(cmd, *a, **kw):
        from subprocess import CompletedProcess
        return CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert detect() == InstallMethod.SOURCE
