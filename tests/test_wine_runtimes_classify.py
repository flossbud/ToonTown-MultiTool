"""Tests for classify_path."""

import sys
import pytest
from services.wine_runtimes import classify_path


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_bottle(root, name):
    bottle = root / name
    install = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    exe = install / "CorporateClash.exe"
    exe.write_text("")
    (bottle / "bottle.yml").write_text(f"Name: {name}\n")
    return exe, bottle


def test_classifies_bottle(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bottles_root = home / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    bottles_root.mkdir(parents=True)
    exe, bottle = _make_bottle(bottles_root, "MyBottle")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    inst = classify_path(str(exe))
    assert inst is not None
    assert inst.launcher == "bottles"
    assert inst.prefix_path == str(bottle)


def test_classifies_steam_proton(tmp_path, monkeypatch):
    home = tmp_path / "home"
    steam_root = home / ".local/share/Steam"
    (steam_root / "steamapps").mkdir(parents=True)
    pfx = steam_root / "steamapps/compatdata/12345/pfx"
    install = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    exe = install / "CorporateClash.exe"
    exe.write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    inst = classify_path(str(exe))
    assert inst is not None
    assert inst.launcher == "steam-proton"
    assert inst.metadata["appid"] == "12345"


def test_classifies_plain_wine_prefix(tmp_path, monkeypatch):
    home = tmp_path / "home"
    prefix = home / "myprefix"
    install = prefix / "drive_c/users/me/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    (prefix / "dosdevices").mkdir()
    (prefix / "dosdevices" / "c:").symlink_to(prefix / "drive_c")
    exe = install / "CorporateClash.exe"
    exe.write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    inst = classify_path(str(exe))
    assert inst is not None
    assert inst.launcher == "wine"
    assert inst.prefix_path == str(prefix)


def test_classifies_lutris(tmp_path, monkeypatch):
    home = tmp_path / "home"
    games_dir = home / ".config/lutris/games"
    games_dir.mkdir(parents=True)
    prefix = home / "Games/corporate-clash"
    install = prefix / "drive_c/users/lutris/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    exe = install / "CorporateClash.exe"
    exe.write_text("")
    yml = games_dir / "corporate-clash.yml"
    yml.write_text(
        "game:\n"
        f"  prefix: {prefix}\n"
        "name: Corporate Clash\n"
        "runner: wine\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    inst = classify_path(str(exe))
    assert inst is not None
    assert inst.launcher == "lutris"
    assert inst.prefix_path == str(prefix)
    assert inst.metadata["lutris_slug"] == "corporate-clash"


def test_returns_none_for_unrecognized_path(tmp_path):
    exe = tmp_path / "random/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert classify_path(str(exe)) is None
