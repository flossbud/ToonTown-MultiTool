"""Tests for discover_lutris."""

import sys
import pytest
from services.wine_runtimes import discover_lutris


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")


def _make_lutris_yaml(games_dir, slug, prefix_path, name="Corporate Clash"):
    yml = games_dir / f"{slug}.yml"
    yml.write_text(
        "game:\n"
        f"  prefix: {prefix_path}\n"
        f"name: {name}\n"
        "runner: wine\n"
    )
    return yml


def _make_prefix_with_cc(prefix_path):
    install = prefix_path / "drive_c/users/lutris/AppData/Local/Corporate Clash"
    install.mkdir(parents=True)
    (install / "CorporateClash.exe").write_text("")


def test_finds_install_via_lutris_yaml(tmp_path, monkeypatch):
    home = tmp_path / "home"
    games_dir = home / ".config/lutris/games"
    games_dir.mkdir(parents=True)
    prefix = home / "Games/corporate-clash"
    prefix.mkdir(parents=True)
    _make_prefix_with_cc(prefix)
    _make_lutris_yaml(games_dir, "corporate-clash", str(prefix))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_lutris()
    assert len(installs) == 1
    inst = installs[0]
    assert inst.launcher == "lutris"
    assert inst.prefix_path == str(prefix)
    assert "Corporate Clash" in inst.display_name


def test_skips_yaml_with_missing_prefix(tmp_path, monkeypatch):
    home = tmp_path / "home"
    games_dir = home / ".config/lutris/games"
    games_dir.mkdir(parents=True)
    _make_lutris_yaml(games_dir, "missing", "/nonexistent/path")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    assert discover_lutris() == []


def test_skips_non_wine_runner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    games_dir = home / ".config/lutris/games"
    games_dir.mkdir(parents=True)
    prefix = home / "Games/cc"
    prefix.mkdir(parents=True)
    _make_prefix_with_cc(prefix)
    yml = games_dir / "cc.yml"
    yml.write_text(
        "game:\n"
        f"  prefix: {prefix}\n"
        "name: CC\nrunner: steam\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    assert discover_lutris() == []
