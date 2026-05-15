"""Tests for discover_bottles."""

import sys
import pytest
from services.wine_runtimes import discover_bottles


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_bottle(root, dir_name, display_name, user="steamuser"):
    bottle_dir = root / dir_name
    install = bottle_dir / "drive_c" / "users" / user / "AppData" / "Local" / "Corporate Clash"
    install.mkdir(parents=True)
    (install / "CorporateClash.exe").write_text("")
    (bottle_dir / "bottle.yml").write_text(
        f"Name: {display_name}\n"
        "Arch: win64\n"
        "Runner: soda-9.0-1\n"
    )
    return bottle_dir


def test_finds_bottle_in_flatpak_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bottles_root = home / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    bottles_root.mkdir(parents=True)
    _make_bottle(bottles_root, "Corporate-Clash", "Corporate Clash")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_bottles()
    assert len(installs) == 1
    inst = installs[0]
    assert inst.launcher == "bottles"
    assert inst.metadata["bottle_name"] == "Corporate-Clash"
    assert inst.metadata["distribution"] == "flatpak"
    assert "Corporate Clash" in inst.display_name


def test_falls_back_to_dir_name_when_bottle_yml_missing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bottles_root = home / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    bottles_root.mkdir(parents=True)
    bottle_dir = bottles_root / "MyBottle"
    install = bottle_dir / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    (install / "CorporateClash.exe").write_text("")
    # Note: no bottle.yml
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_bottles()
    assert len(installs) == 1
    assert "MyBottle" in installs[0].display_name


def test_finds_bottle_in_native_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bottles_root = home / ".local/share/bottles/bottles"
    bottles_root.mkdir(parents=True)
    _make_bottle(bottles_root, "Native-Bottle", "Native Bottle")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_bottles()
    assert len(installs) == 1
    assert installs[0].metadata["distribution"] == "native"
