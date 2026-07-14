"""Tests for find_cc_engine_path."""

import sys
import pytest


# Test runs on all platforms (Linux, macOS, Windows).
# Windows detection uses different paths but the logic is the same.


def test_find_cc_engine_path_returns_first_install_dir(tmp_path, monkeypatch):
    """Test Linux/Bottles detection path."""
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
    """Test when no installs found."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "_appdata"))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    from services.cc_login_service import find_cc_engine_path
    assert find_cc_engine_path() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_find_cc_engine_path_macos_detects_app_bundle(tmp_path, monkeypatch):
    """Test macOS detection of Corporate Clash .app bundle."""
    # Create a fake macOS CC installation
    app_support = tmp_path / "Library" / "Application Support" / "Corporate Clash"
    app_support.mkdir(parents=True)
    app_bundle = app_support / "CorporateClash.app" / "Contents" / "MacOS"
    app_bundle.mkdir(parents=True)
    (app_bundle / "corporateclash").write_text("")
    
    # Mock expanduser to return our tmp_path
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: str(tmp_path) if p == "~" else p)
    
    from services.cc_login_service import find_cc_engine_path
    result = find_cc_engine_path()
    assert result == str(app_support)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_find_cc_engine_path_macos_none_when_no_bundle(tmp_path, monkeypatch):
    """Test macOS returns None when .app bundle doesn't exist."""
    # Create the data dir but without the .app bundle
    app_support = tmp_path / "Library" / "Application Support" / "Corporate Clash"
    app_support.mkdir(parents=True)
    
    # Mock expanduser to return our tmp_path
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: str(tmp_path) if p == "~" else p)
    
    from services.cc_login_service import find_cc_engine_path
    assert find_cc_engine_path() is None
