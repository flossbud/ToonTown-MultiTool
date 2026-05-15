"""Tests for discover_steam_proton."""

import sys
import pytest
from services.wine_runtimes import discover_steam_proton


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_compatdata(steam_root, appid, with_proton_marker=True):
    compatdata = steam_root / "steamapps/compatdata" / str(appid) / "pfx"
    install = compatdata / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    (install / "CorporateClash.exe").write_text("")
    # Steam writes config_info next to pfx with the Proton version name.
    if with_proton_marker:
        cfg = compatdata.parent / "config_info"
        cfg.write_text("/home/user/.local/share/Steam/steamapps/common/Proton 8.0\n")
    return compatdata.parent


def test_finds_compatdata_install(tmp_path, monkeypatch):
    home = tmp_path / "home"
    steam_root = home / ".local/share/Steam"
    (steam_root / "steamapps").mkdir(parents=True)
    _make_compatdata(steam_root, 2895030471)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_steam_proton()
    assert len(installs) == 1
    inst = installs[0]
    assert inst.launcher == "steam-proton"
    assert inst.metadata["appid"] == "2895030471"
    assert "Proton 8.0" in (inst.metadata.get("proton_dir") or "")


def test_display_name_falls_back_to_appid(tmp_path, monkeypatch):
    home = tmp_path / "home"
    steam_root = home / ".local/share/Steam"
    (steam_root / "steamapps").mkdir(parents=True)
    _make_compatdata(steam_root, 12345, with_proton_marker=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_steam_proton()
    assert len(installs) == 1
    assert "12345" in installs[0].display_name
