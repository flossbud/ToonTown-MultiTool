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


import struct


def _make_shortcuts_vdf(steam_root, appid: int, name: str):
    """Write a minimal shortcuts.vdf with one shortcut entry.

    The format is a binary VDF blob. We write just enough structure to
    exercise the byte-scanner: type-tagged appid (int32 LE, unsigned) and
    AppName (string) keys.
    """
    userdata = steam_root / "userdata" / "12345678" / "config"
    userdata.mkdir(parents=True)
    vdf = userdata / "shortcuts.vdf"
    # Minimal shortcut entry: \x02appid\x00<le-uint32>\x01AppName\x00<name>\x00\x08\x08
    # The \x08\x08 are the entry terminators Steam writes; not strictly
    # required for the byte-scanner but reproduces realistic shape.
    entry = (
        b"\x02appid\x00" + struct.pack("<I", appid)
        + b"\x01AppName\x00" + name.encode("utf-8") + b"\x00"
        + b"\x08\x08"
    )
    # Wrap with a single entry index "0" (typical VDF top-level shape).
    header = b"\x00shortcuts\x00\x000\x00"
    vdf.write_bytes(header + entry + b"\x08\x08")
    return vdf


def test_shortcuts_vdf_resolves_display_name(tmp_path, monkeypatch):
    """When shortcuts.vdf has a matching entry, display name comes from VDF
    rather than the appid fallback."""
    home = tmp_path / "home"
    steam_root = home / ".local/share/Steam"
    (steam_root / "steamapps").mkdir(parents=True)
    appid = 2895030471  # high-bit-set, like real non-Steam shortcuts
    _make_compatdata(steam_root, appid)
    _make_shortcuts_vdf(steam_root, appid, "Corporate Clash")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_steam_proton()
    assert len(installs) == 1
    assert "Corporate Clash" in installs[0].display_name
    # Confirm we got the VDF-resolved name, not the appid fallback.
    assert str(appid) not in installs[0].display_name
