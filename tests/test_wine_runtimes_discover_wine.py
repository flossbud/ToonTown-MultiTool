"""Tests for discover_plain_wine."""

import sys
import pytest
from services.wine_runtimes import discover_plain_wine


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_wine_prefix(root, prefix_name, user="user", under_appdata=True):
    prefix = root / prefix_name
    if under_appdata:
        rel = "drive_c/users/{}/AppData/Local/Corporate Clash".format(user)
    else:
        rel = "drive_c/Program Files/Corporate Clash"
    install = prefix / rel
    install.mkdir(parents=True)
    (install / "CorporateClash.exe").write_text("")
    # The classifier looks for dosdevices/c: as the plain-Wine marker.
    (prefix / "dosdevices").mkdir()
    (prefix / "dosdevices" / "c:").symlink_to(prefix / "drive_c")
    return prefix


def test_finds_install_in_dot_wine(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    _make_wine_prefix(home, ".wine")
    installs = discover_plain_wine()
    assert len(installs) == 1
    assert installs[0].launcher == "wine"
    assert installs[0].prefix_path == str(home / ".wine")


def test_finds_install_in_wineprefixes_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".local" / "share" / "wineprefixes").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    _make_wine_prefix(home / ".local" / "share" / "wineprefixes", "myprefix")
    installs = discover_plain_wine()
    assert len(installs) == 1
    assert installs[0].launcher == "wine"
    assert "myprefix" in installs[0].display_name


def test_empty_when_no_prefixes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    assert discover_plain_wine() == []
