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
    """The TTR portrait widget paints the circle outline when set.

    Note: the widget hard-caps at 64x64 via setMaximumSize. Don't override.
    With width=64, cx=cy=32, r=30, and outline thick (width=4, inset=2),
    the outline ring is at radius 28..30 from center, so the leftmost
    outline pixel is at x = cx - 30 = 2 (rect outer edge) through x = 4."""
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
    # Use the widget's actual size (64x64 - hard-capped).
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    pm = w.grab()
    img = pm.toImage()
    # Walk inward at vertical center looking for the FIRST YELLOW pixel.
    # The widget background may paint solid pixels in the corners, so we
    # filter for the outline color specifically rather than any opaque pixel.
    cy = 32  # 64 / 2
    found_yellow = False
    for x in range(0, 10):
        px = img.pixelColor(x, cy)
        if px.red() > 200 and px.green() > 180 and px.blue() < 120:
            found_yellow = True
            break
    assert found_yellow, (
        f"never saw a yellow outline pixel walking inward from x=0..9 at y={cy}. "
        f"sampled colors: {[img.pixelColor(x, cy).name() for x in range(0, 10)]}"
    )


def test_cc_portrait_draws_circle_outline_when_set(qt_app, monkeypatch, tmp_path):
    """CC mode renders via paint_cc_badge. The badge function must accept
    the new circle_outline kwarg and draw the ring on top."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtGui import QColor
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager

    mgr = ToonCustomizationsManager()
    mgr.set("cc", "CCToon", {
        "portrait": {"outline": {"color": "#ffd84a", "width": "thick"}}
    })
    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("cc")
    w.set_toon_name("CCToon")
    # CC mode requires _cc_mode + _cc_skin to engage the CC paint path.
    w._cc_mode = True
    w._cc_skin = QColor("#d9a04e")
    pm = w.grab()
    img = pm.toImage()
    # Widget is 64x64 (hard-capped). Walk inward at vertical center
    # looking for the FIRST YELLOW pixel.
    cy = 32
    found_yellow = False
    for x in range(0, 10):
        px = img.pixelColor(x, cy)
        if px.red() > 200 and px.green() > 180 and px.blue() < 120:
            found_yellow = True
            break
    assert found_yellow, (
        f"never saw a yellow outline pixel walking inward at y={cy}. "
        f"sampled: {[img.pixelColor(x, cy).name() for x in range(0, 10)]}"
    )
