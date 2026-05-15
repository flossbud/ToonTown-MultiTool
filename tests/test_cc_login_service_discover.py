"""Tests for the rewired find_cc_engine_path."""

import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def test_find_cc_engine_path_returns_first_install_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bottles_root = home / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    bottles_root.mkdir(parents=True)
    bottle = bottles_root / "X"
    install_dir = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install_dir.mkdir(parents=True)
    (install_dir / "CorporateClash.exe").write_text("")
    (bottle / "bottle.yml").write_text("Name: X\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    from services.cc_login_service import find_cc_engine_path
    result = find_cc_engine_path()
    assert result == str(install_dir)


def test_find_cc_engine_path_returns_none_when_no_installs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "_appdata"))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    from services.cc_login_service import find_cc_engine_path
    assert find_cc_engine_path() is None
