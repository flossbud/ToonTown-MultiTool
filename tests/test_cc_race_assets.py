"""Tests for CC race asset lookup."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from utils import cc_race_assets


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_lowercase_match():
    assert cc_race_assets.asset_stem_for_species("DOG") == "dog"
    assert cc_race_assets.asset_stem_for_species("DUCK") == "duck"
    assert cc_race_assets.asset_stem_for_species("MOUSE") == "mouse"


def test_alias_match():
    # CC's binary names "CROCODILE" but the asset is alligator.png.
    assert cc_race_assets.asset_stem_for_species("CROCODILE") == "alligator"


def test_unknown_species_returns_none():
    assert cc_race_assets.asset_stem_for_species("NOT_A_REAL_SPECIES") is None


def test_none_input_returns_none():
    assert cc_race_assets.asset_stem_for_species(None) is None
    assert cc_race_assets.asset_stem_for_species("") is None


def test_species_with_no_png_returns_none(monkeypatch, tmp_path):
    # FROG is in CC's binary but we have no frog.png yet.
    # Point RACE_ASSETS_DIR at an empty temp dir so even DOG returns None.
    monkeypatch.setattr(cc_race_assets, "_asset_dir_override", str(tmp_path))
    assert cc_race_assets.asset_stem_for_species("DOG") is None


def test_load_race_pixmap_returns_none_for_unknown(qapp):
    assert cc_race_assets.load_race_pixmap("not_a_real_stem") is None


def test_load_race_pixmap_caches_by_stem(qapp):
    # Two calls with the same stem return the same QPixmap instance.
    pm1 = cc_race_assets.load_race_pixmap("dog")
    pm2 = cc_race_assets.load_race_pixmap("dog")
    assert pm1 is not None
    assert pm1 is pm2
