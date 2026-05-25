"""Tests for ToonPortraitWidget's delegation to RenditionPoseFetcher.

The widget no longer fetches Rendition pixmaps inline - it asks the
shared RenditionPoseFetcher and consumes the public pose_ready signal."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_set_dna_requests_portrait_pose_when_no_override(qt_app, monkeypatch, tmp_path):
    """Default behavior: set_dna asks the fetcher for the 'portrait' pose."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None  # reset singleton
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )

    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_customizations_manager(ToonCustomizationsManager())
    w.set_game("ttr")
    w.set_toon_name("Flossbud")

    requested.clear()
    w.set_dna("dna-foo")
    assert ("dna-foo", "portrait") in requested


def test_set_dna_uses_pose_override_from_manager(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "portrait-grin"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    requested.clear()
    w.set_dna("dna-foo")

    assert ("dna-foo", "portrait-grin") in requested


def test_set_pose_triggers_refetch(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(ToonCustomizationsManager())
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    w.set_dna("dna-foo")
    requested.clear()
    w.set_pose("waving")
    assert ("dna-foo", "waving") in requested


def test_set_dna_none_clears_pixmap(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher, "request", lambda *a, **k: None,
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from PySide6.QtGui import QPixmap
    w = ToonPortraitWidget(1)
    pm = QPixmap(10, 10); pm.fill()
    w._pixmap = pm
    w.set_dna(None)
    assert w._pixmap is None


def test_set_toon_name_after_set_dna_picks_up_saved_pose(qt_app, monkeypatch, tmp_path):
    """Regression: on app restart, the data ingestion path calls
    `set_dna()` before `set_toon_name()`. The first call resolves the
    pose against an empty toon name and asks for "portrait". When the
    name finally arrives, the widget must re-check the manager and
    refetch the saved pose if it differs."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "portrait-grin"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    # Simulate the real-world order: set_dna FIRST (with no name yet),
    # then set_toon_name catches up.
    w.set_dna("dna-foo")
    # First fetch is for the default "portrait" (no name to look up).
    assert ("dna-foo", "portrait") in requested
    requested.clear()

    w.set_toon_name("Flossbud")
    # Now that the name is set, the widget must refetch the saved pose.
    assert ("dna-foo", "portrait-grin") in requested
    assert w._pose == "portrait-grin"


def test_set_game_after_set_dna_picks_up_saved_pose(qt_app, monkeypatch, tmp_path):
    """Sister test: if set_game runs after set_dna + set_toon_name,
    the widget re-resolves the pose under the new game namespace."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "waving"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_toon_name("Flossbud")
    w.set_dna("dna-foo")  # game not yet set → default portrait
    assert ("dna-foo", "portrait") in requested
    requested.clear()

    w.set_game("ttr")
    assert ("dna-foo", "waving") in requested
    assert w._pose == "waving"


def test_toon_portrait_widget_draws_circle_outline_when_set(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher, "request", lambda *a, **k: None
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager

    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {
        "portrait": {
            "color": "#000000",
            "outline": {"color": "#ffd84a", "width": "thick"},
        },
    })
    w = ToonPortraitWidget(1)
    w.setMaximumSize(16777215, 16777215)  # lift default 64×64 cap for this render test
    w.resize(96, 96)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    pm = w.grab()
    img = pm.toImage()
    # Walk inward from the left edge at vertical center until alpha > 0;
    # that should be the outline color.
    cy = 48
    for x in range(0, 12):
        px = img.pixelColor(x, cy)
        if px.alpha() > 0:
            assert px.red() > 200 and px.green() > 180 and px.blue() < 120, (
                f"pixel ({x},{cy}) = {px.name()}, expected outline yellow"
            )
            return
    raise AssertionError("Never saw an opaque pixel near the left edge")
