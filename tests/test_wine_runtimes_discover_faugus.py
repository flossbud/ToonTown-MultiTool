"""Tests for discover_faugus — catalog-based discovery."""

import json
import os
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_prefix_with_cc(prefix: str) -> str:
    install_dir = os.path.join(
        prefix, "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    )
    os.makedirs(install_dir)
    exe = os.path.join(install_dir, "CorporateClash.exe")
    with open(exe, "w") as f:
        f.write("")
    return exe


def _write_flatpak_catalog(home, entries):
    catalog = home / ".var/app/io.github.Faugus.faugus-launcher/config/faugus-launcher/games.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps(entries))
    return catalog


def _write_native_catalog(home, entries):
    catalog = home / ".config/faugus-launcher/games.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps(entries))
    return catalog


def _patch_home(monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))


def test_finds_cc_via_flatpak_catalog(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/corporate-clash"
    prefix.mkdir(parents=True)
    _make_prefix_with_cc(str(prefix))
    _write_flatpak_catalog(home, [{
        "gameid": "corporate-clash",
        "title": "Corporate Clash",
        "prefix": str(prefix),
        "path": f"{prefix}/drive_c/Program Files/Corporate Clash/new_launcher.exe",
        "runner": "Proton-CachyOS Latest",
    }])
    _patch_home(monkeypatch, home)
    installs = discover_faugus()
    assert len(installs) == 1
    inst = installs[0]
    assert inst.launcher == "faugus"
    assert inst.prefix_path == str(prefix)
    assert inst.display_name == "Faugus · Corporate Clash"
    assert inst.metadata["faugus_runner"] == "Proton-CachyOS Latest"
    assert inst.metadata["faugus_install_kind"] == "flatpak"
    assert inst.metadata["faugus_gameid"] == "corporate-clash"


def test_finds_cc_via_native_catalog(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/cc"
    prefix.mkdir(parents=True)
    _make_prefix_with_cc(str(prefix))
    _write_native_catalog(home, [{
        "gameid": "cc",
        "title": "Corporate Clash",
        "prefix": str(prefix),
        "path": f"{prefix}/drive_c/Program Files/Corporate Clash/new_launcher.exe",
        "runner": "GE-Proton9-1",
    }])
    _patch_home(monkeypatch, home)
    installs = discover_faugus()
    assert len(installs) == 1
    assert installs[0].metadata["faugus_install_kind"] == "native"
    assert installs[0].metadata["faugus_runner"] == "GE-Proton9-1"


def test_skips_non_cc_entries(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    other = home / "Faugus/some-other-game"
    other.mkdir(parents=True)
    _make_prefix_with_cc(str(other))  # has CC.exe but title says otherwise
    _write_flatpak_catalog(home, [{
        "gameid": "some-other-game",
        "title": "Some Other Game",
        "prefix": str(other),
        "path": f"{other}/some_other.exe",
        "runner": "Proton 8.0",
    }])
    _patch_home(monkeypatch, home)
    assert discover_faugus() == []


def test_catalog_missing_returns_empty(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    _patch_home(monkeypatch, home)
    assert discover_faugus() == []


def test_malformed_catalog_logged_and_skipped(tmp_path, monkeypatch, capsys):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    catalog = home / ".config/faugus-launcher/games.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{not json")
    _patch_home(monkeypatch, home)
    assert discover_faugus() == []
    captured = capsys.readouterr()
    assert "malformed catalog" in captured.out


def test_catalog_entry_with_missing_prefix_on_disk_skipped(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    _write_flatpak_catalog(home, [{
        "gameid": "cc",
        "title": "Corporate Clash",
        "prefix": "/nonexistent/path",
        "path": "/nonexistent/path/x.exe",
        "runner": "Proton",
    }])
    _patch_home(monkeypatch, home)
    assert discover_faugus() == []


def test_prefix_without_cc_exe_skipped(tmp_path, monkeypatch):
    """User installed Faugus + CC but never ran new_launcher.exe — prefix
    exists, has structural markers, but CorporateClash.exe was never
    downloaded. Discovery emits nothing."""
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/corporate-clash"
    prefix.mkdir(parents=True)
    # Make the prefix structurally complete but lacking CC.exe.
    (prefix / "drive_c").mkdir()
    (prefix / "drive_c/Program Files/Corporate Clash").mkdir(parents=True)
    (prefix / "drive_c/Program Files/Corporate Clash/new_launcher.exe").write_text("")
    _write_flatpak_catalog(home, [{
        "gameid": "corporate-clash",
        "title": "Corporate Clash",
        "prefix": str(prefix),
        "path": str(prefix / "drive_c/Program Files/Corporate Clash/new_launcher.exe"),
        "runner": "Proton",
    }])
    _patch_home(monkeypatch, home)
    assert discover_faugus() == []


def test_both_catalogs_present_dedupes_to_one(tmp_path, monkeypatch):
    from services.wine_runtimes import discover_faugus
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/corporate-clash"
    prefix.mkdir(parents=True)
    _make_prefix_with_cc(str(prefix))
    entry = {
        "gameid": "corporate-clash",
        "title": "Corporate Clash",
        "prefix": str(prefix),
        "path": f"{prefix}/drive_c/Program Files/Corporate Clash/new_launcher.exe",
        "runner": "Proton",
    }
    _write_flatpak_catalog(home, [entry])
    _write_native_catalog(home, [entry])
    _patch_home(monkeypatch, home)
    installs = discover_faugus()
    assert len(installs) == 1
    # Flatpak is probed first in _FAUGUS_GAMES_JSON_PATHS, so Flatpak wins.
    assert installs[0].metadata["faugus_install_kind"] == "flatpak"
