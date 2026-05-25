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
