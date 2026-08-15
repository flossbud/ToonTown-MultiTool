"""One asset resolver for the whole app (replaces three private copies)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.asset_paths import asset_path


def test_resolves_under_repo_assets():
    p = asset_path("ttr.png")
    assert p.endswith(os.path.join("assets", "ttr.png"))
    assert os.path.isfile(p), f"{p} should exist in the repo"


def test_honours_meipass(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/frozen", raising=False)
    assert asset_path("x.png") == os.path.join("/frozen", "assets", "x.png")


def test_grandstand_backdrop_art_present():
    """Both banner files the hero and selector need (handoff §10)."""
    for name in ("ttr-banner-pattern.png", "cc-banner-skyline.png"):
        assert os.path.isfile(asset_path(name)), f"missing assets/{name}"


def test_keysets_and_launch_tab_delegate():
    """No second implementation may survive this task."""
    from utils.widgets.keysets import _assets
    import tabs.launch_tab as lt
    assert _assets.asset_path is asset_path
    assert lt._asset_path is asset_path
