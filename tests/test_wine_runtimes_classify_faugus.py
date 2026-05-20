"""Tests for classify_path's Faugus recognition."""

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


def _patch_home(monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(home)))


def test_classify_returns_faugus_when_in_known_prefix(tmp_path, monkeypatch):
    from services.wine_runtimes import classify_path
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/corporate-clash"
    prefix.mkdir(parents=True)
    exe = _make_prefix_with_cc(str(prefix))
    catalog = home / ".config/faugus-launcher/games.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps([{
        "gameid": "corporate-clash",
        "title": "Corporate Clash",
        "prefix": str(prefix),
        "path": f"{prefix}/drive_c/Program Files/Corporate Clash/new_launcher.exe",
        "runner": "Proton-CachyOS Latest",
    }]))
    _patch_home(monkeypatch, home)
    install = classify_path(exe)
    assert install is not None
    assert install.launcher == "faugus"
    assert install.prefix_path == str(prefix)
    assert install.metadata["faugus_install_kind"] == "native"
    assert install.metadata["faugus_runner"] == "Proton-CachyOS Latest"


def test_classify_falls_through_to_wine_when_faugus_catalog_unaware(tmp_path, monkeypatch):
    """An exe inside a prefix Faugus doesn't know about classifies as
    plain wine (dosdevices fallback)."""
    from services.wine_runtimes import classify_path
    home = tmp_path / "home"
    home.mkdir()
    prefix = home / "Faugus/some-prefix"
    prefix.mkdir(parents=True)
    # Has dosdevices, no Faugus catalog entry.
    (prefix / "dosdevices").mkdir()
    exe = _make_prefix_with_cc(str(prefix))
    _patch_home(monkeypatch, home)
    install = classify_path(exe)
    assert install is not None
    assert install.launcher == "wine"
