"""Tests for CCRaceOverridesManager persistence."""

from __future__ import annotations

import json
import os

import pytest

from utils.cc_race_overrides_manager import CCRaceOverridesManager


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Redirect the manager's config dir into tmp_path."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_empty_when_no_file(isolated_config):
    m = CCRaceOverridesManager()
    assert m.get("Flossbud") is None
    assert m.all() == {}


def test_set_and_get(isolated_config):
    m = CCRaceOverridesManager()
    m.set("Flossbud", "dog")
    assert m.get("Flossbud") == "dog"


def test_clear_removes_entry(isolated_config):
    m = CCRaceOverridesManager()
    m.set("Flossbud", "dog")
    m.clear("Flossbud")
    assert m.get("Flossbud") is None


def test_clear_missing_key_is_noop(isolated_config):
    m = CCRaceOverridesManager()
    m.clear("Nobody")  # should not raise
    assert m.all() == {}


def test_persistence_across_instances(isolated_config):
    m1 = CCRaceOverridesManager()
    m1.set("Flossbud", "dog")
    m1.set("Soupy", "mouse")

    m2 = CCRaceOverridesManager()
    assert m2.get("Flossbud") == "dog"
    assert m2.get("Soupy") == "mouse"


def test_corrupt_json_is_empty(isolated_config):
    path = isolated_config / "cc_race_overrides.json"
    path.write_text("{ not valid json ")
    m = CCRaceOverridesManager()
    assert m.all() == {}


def test_file_uses_atomic_write(isolated_config):
    m = CCRaceOverridesManager()
    m.set("Flossbud", "dog")
    final_path = isolated_config / "cc_race_overrides.json"
    tmp_path = isolated_config / "cc_race_overrides.json.tmp"
    assert final_path.exists()
    # The tmp file should be cleaned up after rename.
    assert not tmp_path.exists()


def test_all_returns_copy(isolated_config):
    m = CCRaceOverridesManager()
    m.set("Flossbud", "dog")
    snapshot = m.all()
    snapshot["Flossbud"] = "cat"
    # Mutation of the returned dict does not leak back.
    assert m.get("Flossbud") == "dog"


def test_config_dir_created_with_strict_perms(isolated_config):
    CCRaceOverridesManager()
    mode = os.stat(isolated_config).st_mode & 0o777
    assert mode == 0o700
