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


def test_get_returns_a_deep_copy(isolated_config):
    """Mutating a NESTED dict from get() must not leak into the store.

    Regression: get() did dict(entry) (shallow), so the nested 'portrait'
    sub-dict was shared by reference with the manager's live in-memory entry.
    Callers mutating entry['portrait'] in place (the customization overlay's
    live preview) polluted the store without ever calling set()."""
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"portrait": {"color": "#fff000"}})
    got = m.get("ttr", "Flossbud")
    got["portrait"]["color"] = "#000000"
    got["portrait"]["pattern"] = {"name": "polka", "color": "#123456"}
    assert m.get("ttr", "Flossbud") == {"portrait": {"color": "#fff000"}}


def test_set_stores_a_deep_copy(isolated_config):
    """Mutating the dict passed to set() after the call must not leak in."""
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    payload = {"portrait": {"transform": {"zoom": 1.5, "rotate": 10.0}}}
    m.set("ttr", "Flossbud", payload)
    payload["portrait"]["transform"]["zoom"] = 99.0
    assert m.get("ttr", "Flossbud") == {
        "portrait": {"transform": {"zoom": 1.5, "rotate": 10.0}}
    }


def test_all_returns_deep_copies(isolated_config):
    """all() must not expose the live nested store either."""
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"portrait": {"color": "#fff000"}})
    snapshot = m.all()
    snapshot["ttr::Flossbud"]["portrait"]["color"] = "#000000"
    assert m.get("ttr", "Flossbud") == {"portrait": {"color": "#fff000"}}


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


def test_migration_from_legacy_file(isolated_config):
    """Existing cc_race_overrides.json with flat name->stem migrates to
    'cc::name' -> {'icon_stem': stem} and the old file is renamed .bak."""
    import json
    legacy = isolated_config / "cc_race_overrides.json"
    legacy.write_text(json.dumps({"Flossbud": "DOG", "OtherToon": "CAT"}))
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.get("cc", "Flossbud") == {"icon_stem": "DOG"}
    assert m.get("cc", "OtherToon") == {"icon_stem": "CAT"}
    assert not legacy.exists()
    assert (isolated_config / "cc_race_overrides.json.bak").exists()


def test_migration_idempotent_when_new_file_exists(isolated_config):
    """If the new file already exists, migration must NOT run -- old file
    stays untouched and existing entries are preserved."""
    import json
    legacy = isolated_config / "cc_race_overrides.json"
    legacy.write_text(json.dumps({"Flossbud": "DOG"}))
    new = isolated_config / "toon_customizations.json"
    new.write_text(json.dumps({"ttr::Existing": {"accent": "#abcdef"}}))
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.get("ttr", "Existing") == {"accent": "#abcdef"}
    assert m.get("cc", "Flossbud") == {}  # not migrated
    assert legacy.exists()                  # not renamed


def test_migration_handles_corrupt_legacy_file(isolated_config):
    """If the legacy file exists but is unreadable JSON, skip migration
    silently and start with an empty store."""
    legacy = isolated_config / "cc_race_overrides.json"
    legacy.write_text("{not json")
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    assert m.all() == {}
    # Corrupt legacy is left alone -- no .bak rename when there was nothing
    # to migrate.
    assert legacy.exists()


def test_pose_field_round_trips(isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    m = ToonCustomizationsManager()
    m.set("ttr", "Flossbud", {"pose": "portrait-grin", "accent": "#56c856"})
    entry = m.get("ttr", "Flossbud")
    assert entry["pose"] == "portrait-grin"
    assert entry["accent"] == "#56c856"
