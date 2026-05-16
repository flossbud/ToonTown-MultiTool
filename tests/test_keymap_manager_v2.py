"""Unit tests for KeymapManager v2 (per-game schema)."""

import json
import os

import pytest

from utils.keymap_manager import KeymapManager


def _make_manager_with_file(tmp_path, contents=None):
    """Create a KeymapManager pointing at a temp config dir."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    path = cfg / "keymaps.json"
    if contents is not None:
        path.write_text(json.dumps(contents))
    # Monkey-patch the config dir through env var (build_flavor reads it)
    os.environ["TTMT_CONFIG_DIR"] = str(cfg)
    try:
        mgr = KeymapManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)
    return mgr, path


class TestFreshInit:
    def test_writes_v2_shape_when_no_file(self, tmp_path):
        mgr, path = _make_manager_with_file(tmp_path)
        data = json.loads(path.read_text())
        assert data["version"] == 2
        assert "ttr" in data and "cc" in data
        assert len(data["ttr"]) == 1
        assert len(data["cc"]) == 1
        assert data["ttr"][0]["name"] == "Default"
        assert data["cc"][0]["name"] == "Default"

    def test_ttr_default_has_baked_bindings(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        ttr = mgr.get_default("ttr")
        assert ttr["forward"] == "w"
        assert ttr["jump"] == "space"
        assert ttr["map"] == "Shift_L"
        assert "sprint" not in ttr

    def test_cc_default_has_baked_bindings_including_sprint(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        cc = mgr.get_default("cc")
        assert cc["forward"] == "w"
        assert cc["book"] == "Escape"
        assert cc["gags"] == "q"
        assert cc["sprint"] == "Shift_L"


class TestReadAPI:
    def test_get_sets_returns_per_game_list(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert isinstance(mgr.get_sets("ttr"), list)
        assert isinstance(mgr.get_sets("cc"), list)
        assert len(mgr.get_sets("ttr")) == 1
        assert len(mgr.get_sets("cc")) == 1

    def test_get_set_names_per_game(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert mgr.get_set_names("ttr") == ["Default"]
        assert mgr.get_set_names("cc") == ["Default"]

    def test_get_action_in_set_ttr(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert mgr.get_action_in_set("ttr", 0, "w") == "forward"
        assert mgr.get_action_in_set("ttr", 0, "space") == "jump"
        assert mgr.get_action_in_set("ttr", 0, "nonexistent") is None

    def test_get_action_in_set_cc(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert mgr.get_action_in_set("cc", 0, "Shift_L") == "sprint"
        assert mgr.get_action_in_set("cc", 0, "Escape") == "book"

    def test_get_key_for_action(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert mgr.get_key_for_action("ttr", 0, "forward") == "w"
        assert mgr.get_key_for_action("cc", 0, "sprint") == "Shift_L"
        assert mgr.get_key_for_action("ttr", 0, "sprint") is None
        assert mgr.get_key_for_action("ttr", 99, "forward") is None

    def test_num_sets_per_game(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        assert mgr.num_sets("ttr") == 1
        assert mgr.num_sets("cc") == 1


class TestUpdateSetKeyGameScope:
    def test_rejects_cc_only_action_on_ttr_set(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("ttr", 0, "sprint", "Shift_L")
        # sprint is CC-only; nothing should land in the TTR set
        assert "sprint" not in mgr.get_default("ttr")

    def test_accepts_shared_action_on_both_games(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("ttr", 0, "forward", "i")
        mgr.update_set_key("cc", 0, "forward", "j")
        assert mgr.get_default("ttr")["forward"] == "i"
        assert mgr.get_default("cc")["forward"] == "j"

    def test_rejects_unknown_game(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("xyz", 0, "forward", "z")
        # No crash, no state change
        assert mgr.get_default("ttr")["forward"] == "w"
