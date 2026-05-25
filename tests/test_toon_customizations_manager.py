"""Tests for ToonCustomizationsManager persistence."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_empty_load_yields_no_entries(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.all() == {}


def test_set_get_roundtrip(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"accent": "#56c856"})
    assert m.get("ttr", "Flossbud") == {"accent": "#56c856"}


def test_get_missing_returns_empty_dict(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.get("ttr", "Nobody") == {}


def test_clear_removes_entry(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("cc", "Flossbud", {"icon_stem": "DOG"})
    m.clear("cc", "Flossbud")
    assert m.get("cc", "Flossbud") == {}


def test_set_empty_dict_removes_entry(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"accent": "#abcdef"})
    m.set("ttr", "Flossbud", {})
    assert m.get("ttr", "Flossbud") == {}


def test_persistence_across_instances(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m1 = ToonCustomizationsManager()
    m1.set("ttr", "Flossbud", {"body": "#101020"})
    m2 = ToonCustomizationsManager()
    assert m2.get("ttr", "Flossbud") == {"body": "#101020"}


def test_get_returns_a_copy(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"accent": "#fff000"})
    got = m.get("ttr", "Flossbud")
    got["accent"] = "#000000"
    assert m.get("ttr", "Flossbud") == {"accent": "#fff000"}


def test_namespace_isolation(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("cc", "Flossbud", {"icon_stem": "DOG"})
    m.set("ttr", "Flossbud", {"accent": "#56c856"})
    assert m.get("cc", "Flossbud") == {"icon_stem": "DOG"}
    assert m.get("ttr", "Flossbud") == {"accent": "#56c856"}


def test_invalid_keys_dropped_on_load(isolated_config):
    """Keys not matching 'game::name' or values not dicts are skipped silently."""
    import json
    path = isolated_config / "toon_customizations.json"
    path.write_text(json.dumps({
        "ttr::Good": {"accent": "#abc123"},
        "Flossbud": {"accent": "#000000"},          # no namespace
        "wrong::Bad": {"accent": "#000000"},        # unknown game
        "ttr::AlsoBad": "not a dict",               # not a dict value
    }))
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.all() == {"ttr::Good": {"accent": "#abc123"}}


def test_atomic_write_cleans_up_tmp_on_oserror(isolated_config, monkeypatch):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", boom)
    m.set("ttr", "Flossbud", {"accent": "#000000"})  # save fails
    monkeypatch.setattr(os, "replace", real_replace)

    # tmp file must be cleaned up
    tmp = isolated_config / "toon_customizations.json.tmp"
    assert not tmp.exists()
