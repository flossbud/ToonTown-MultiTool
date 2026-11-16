"""Shared asset resolution for the scoped launcher-adjacent call sites."""
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


def test_launcher_adjacent_asset_call_sites_delegate(monkeypatch):
    """Launcher, credits, keysets, settings, and reorder use the shared resolver."""
    from utils.widgets.keysets import _assets
    import utils.widgets.account_reorder_dialog as account_reorder
    import tabs.credits_tab
    import tabs.launch_tab as lt

    assert _assets.asset_path is asset_path
    assert account_reorder._asset_path is asset_path
    assert tabs.credits_tab._asset_path is asset_path
    assert lt._asset_path is asset_path

    resolved = object()
    import utils.widgets.settings_rows as settings_rows
    monkeypatch.setattr(settings_rows, "asset_path", lambda name: resolved)
    assert settings_rows.SettingsRows._asset_path(None, "x.png") is resolved
