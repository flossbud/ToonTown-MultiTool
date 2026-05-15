"""Tests for is_launcher_available and discover_cc_installs."""

import sys
import pytest
from services.wine_runtimes import (
    is_launcher_available,
    discover_cc_installs,
    WineInstall,
)


def test_native_is_always_available():
    assert is_launcher_available("native") is True


def test_unknown_launcher_returns_false():
    assert is_launcher_available("nonsense") is False


@pytest.mark.skipif(sys.platform == "win32", reason="Linux only")
def test_wine_availability_checks_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert is_launcher_available("wine") is False


def test_discover_cc_installs_dedupes_and_sorts(tmp_path, monkeypatch):
    """Bottles entry is preferred over a plain-wine duplicate of the same realpath."""
    home = tmp_path / "home"
    bottles_root = home / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    bottles_root.mkdir(parents=True)
    bottle = bottles_root / "X"
    install_dir = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash"
    install_dir.mkdir(parents=True)
    (install_dir / "CorporateClash.exe").write_text("")
    (bottle / "bottle.yml").write_text("Name: X\n")
    # Plain-wine symlink pointing at the same exe
    plain_root = home / ".local/share/wineprefixes/aliased"
    aliased_install = plain_root / "drive_c/users/me/AppData/Local/Corporate Clash"
    aliased_install.mkdir(parents=True)
    import os
    os.symlink(install_dir / "CorporateClash.exe", aliased_install / "CorporateClash.exe")
    (plain_root / "dosdevices").mkdir()
    (plain_root / "dosdevices" / "c:").symlink_to(plain_root / "drive_c")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))
    installs = discover_cc_installs()
    assert len(installs) == 1
    assert installs[0].launcher == "bottles"
