"""Tests for RenditionPoseFetcher: disk cache + async fetch + paint-race guards."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    # Reset the singleton between tests.
    from utils import rendition_poses
    rendition_poses.RenditionPoseFetcher._instance = None
    yield tmp_path
    rendition_poses.RenditionPoseFetcher._instance = None


def test_pose_names_tuple_has_13_entries():
    from utils.rendition_poses import POSE_NAMES
    assert isinstance(POSE_NAMES, tuple)
    assert len(POSE_NAMES) == 13
    # Spot-check the canonical first + last + a portrait-variant.
    assert POSE_NAMES[0] == "portrait"
    assert "portrait-grin" in POSE_NAMES
    assert "laffmeter" in POSE_NAMES


def test_cache_dir_under_config_dir(qapp, isolated_cache):
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    cache = fetcher.cache_dir()
    assert cache == os.path.join(str(isolated_cache), "rendition_cache")
    assert os.path.isdir(cache)
