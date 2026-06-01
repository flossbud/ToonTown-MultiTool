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


class TestV1Migration:
    def test_v1_list_migrates_to_v2(self, tmp_path):
        legacy = [
            {"name": "Default", "up": "w", "left": "a", "down": "s",
             "right": "d", "jump": "space", "book": "Alt_L",
             "gags": "g", "tasks": "t", "map": "Shift_L"},
            {"name": "Arrows", "up": "Up", "left": "Left", "down": "Down",
             "right": "Right", "jump": "Control_L", "book": "Alt_R",
             "gags": "g", "tasks": "t", "map": "Shift_R"},
        ]
        mgr, path = _make_manager_with_file(tmp_path, legacy)
        data = json.loads(path.read_text())
        assert data["version"] == 2
        assert len(data["ttr"]) == 2
        assert len(data["cc"]) == 1

    def test_v1_up_renamed_to_forward(self, tmp_path):
        legacy = [{"name": "Default", "up": "w", "down": "s",
                   "left": "a", "right": "d", "jump": "space",
                   "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L"}]
        mgr, _ = _make_manager_with_file(tmp_path, legacy)
        ttr = mgr.get_default("ttr")
        assert ttr["forward"] == "w"
        assert ttr["reverse"] == "s"
        assert "up" not in ttr
        assert "down" not in ttr

    def test_v1_migration_seeds_cc_default(self, tmp_path):
        legacy = [{"name": "Default", "up": "w", "down": "s",
                   "left": "a", "right": "d", "jump": "space",
                   "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L"}]
        mgr, _ = _make_manager_with_file(tmp_path, legacy)
        cc = mgr.get_default("cc")
        assert cc["forward"] == "w"
        assert cc["sprint"] == "Shift_L"
        assert cc["book"] == "Escape"

    def test_v2_backfill_adds_missing_actions(self, tmp_path):
        v2 = {
            "version": 2,
            "ttr": [{"name": "Default", "forward": "w"}],  # everything else missing
            "cc": [{"name": "Default"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        ttr = mgr.get_default("ttr")
        assert ttr["forward"] == "w"
        assert ttr["jump"] == "space"  # backfilled from registry
        assert ttr["map"] == "Shift_L"
        cc = mgr.get_default("cc")
        assert cc["sprint"] == "Shift_L"  # backfilled

    def test_unknown_shape_resets(self, tmp_path):
        # A dict without version=2 is treated as unrecognized -> reset
        mgr, _ = _make_manager_with_file(tmp_path, {"version": 1, "foo": "bar"})
        assert mgr.num_sets("ttr") == 1
        assert mgr.num_sets("cc") == 1
        # Reset should produce valid seeded defaults, not empty stubs
        assert mgr.get_default("ttr")["forward"] == "w"
        assert mgr.get_default("cc")["sprint"] == "Shift_L"


class TestWriteAPI:
    def test_add_set_adds_to_correct_game(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.add_set("ttr", name="Arrows")
        assert mgr.num_sets("ttr") == 2
        assert mgr.num_sets("cc") == 1
        assert mgr.get_set_names("ttr") == ["Default", "Arrows"]

    def test_add_set_caps_at_max(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        for _ in range(KeymapManager.MAX_SETS_PER_GAME + 2):
            mgr.add_set("ttr")
        assert mgr.num_sets("ttr") == KeymapManager.MAX_SETS_PER_GAME

    def test_delete_set_removes_non_default(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.add_set("ttr", name="Arrows")
        mgr.delete_set("ttr", 1)
        assert mgr.num_sets("ttr") == 1

    def test_delete_set_refuses_default(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.delete_set("ttr", 0)
        assert mgr.num_sets("ttr") == 1
        assert mgr.get_default("ttr")["forward"] == "w"

    def test_update_set_key_writes(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("ttr", 0, "forward", "Up")
        assert mgr.get_key_for_action("ttr", 0, "forward") == "Up"

    def test_update_set_key_ignores_unknown_action(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("ttr", 0, "fly", "f")
        # No-op, no crash; the set is unchanged
        assert "fly" not in mgr.get_default("ttr")

    def test_update_set_name(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.add_set("ttr", name="Arrows")
        mgr.update_set_name("ttr", 1, "Joystick")
        assert mgr.get_set_names("ttr") == ["Default", "Joystick"]

    def test_add_set_does_not_notify_when_capped(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        for _ in range(KeymapManager.MAX_SETS_PER_GAME):
            mgr.add_set("ttr")
        calls = []
        mgr.on_change(lambda: calls.append(1))
        mgr.add_set("ttr")  # over the cap; should be a no-op
        assert calls == []

    def test_delete_set_does_not_notify_when_oob(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        calls = []
        mgr.on_change(lambda: calls.append(1))
        mgr.delete_set("ttr", 99)  # out of range
        assert calls == []

    def test_update_set_key_does_not_notify_when_oob(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        calls = []
        mgr.on_change(lambda: calls.append(1))
        mgr.update_set_key("ttr", 99, "forward", "Up")  # out-of-range set index
        assert calls == []

    def test_update_set_key_noop_when_value_unchanged(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        calls = []
        mgr.on_change(lambda: calls.append(1))
        # The default already has forward=w; writing w again is a no-op
        mgr.update_set_key("ttr", 0, "forward", "w")
        assert calls == []
        # Writing a different value triggers exactly one notification
        mgr.update_set_key("ttr", 0, "forward", "i")
        assert calls == [1]


class TestHasConflicts:
    def test_default_has_no_conflicts(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        has, pairs = mgr.has_conflicts("ttr", 0)
        assert has is False
        assert pairs == []

    def test_constructed_conflict(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("ttr", 0, "gags", "w")  # collides with forward=w
        has, pairs = mgr.has_conflicts("ttr", 0)
        assert has is True
        assert ("forward", "gags") in pairs or ("gags", "forward") in pairs

    def test_cc_sprint_conflict(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        mgr.update_set_key("cc", 0, "sprint", "w")  # collides with cc forward=w
        has, pairs = mgr.has_conflicts("cc", 0)
        assert has is True


class TestPerformActionBackfill:
    """`action` is a TTR-only logical action (see Task 1). The existing
    backfill loop must add it to TTR sets and never to CC sets."""

    def test_fresh_ttr_default_has_action_delete(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        ttr = mgr.get_default("ttr")
        assert ttr["action"] == "Delete"

    def test_fresh_cc_default_has_no_action(self, tmp_path):
        mgr, _ = _make_manager_with_file(tmp_path)
        cc = mgr.get_default("cc")
        assert "action" not in cc

    def test_legacy_ttr_set_without_action_gets_delete(self, tmp_path):
        """A keymaps.json file written by an older TTMT (no `action` in
        any set) must have `action` backfilled to `Delete` on load."""
        v2 = {
            "version": 2,
            "ttr": [
                {"name": "Default", "forward": "w", "reverse": "s",
                 "left": "a", "right": "d", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L"},
            ],
            "cc": [{"name": "Default"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        ttr = mgr.get_default("ttr")
        assert ttr["action"] == "Delete"

    def test_legacy_alternate_ttr_set_action_mirrors_default(self, tmp_path):
        """An alternate set that lacks `action` mirrors set 0's value
        per the existing _backfill_missing_actions rule (set 0 backfills
        from the registry default, then alternates mirror set 0)."""
        v2 = {
            "version": 2,
            "ttr": [
                {"name": "Default", "forward": "w", "reverse": "s",
                 "left": "a", "right": "d", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L"},
                {"name": "Arrows", "forward": "Up", "reverse": "Down",
                 "left": "Left", "right": "Right", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L"},
            ],
            "cc": [{"name": "Default"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        ttr_default = mgr.get_set("ttr", 0)
        ttr_alt = mgr.get_set("ttr", 1)
        assert ttr_default["action"] == "Delete"
        assert ttr_alt["action"] == "Delete"

    def test_cc_set_never_gets_action_backfilled(self, tmp_path):
        v2 = {
            "version": 2,
            "ttr": [{"name": "Default"}],
            "cc": [{"name": "Default"}, {"name": "Alt"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        for i in range(mgr.num_sets("cc")):
            assert "action" not in mgr.get_set("cc", i)


class TestCanonicalizeStoredKeys:
    """Migration: persisted 'backslash' (X11 keysym name) must be rewritten
    to '\\' (raw char) on load so pynput events match the stored value."""

    def test_backslash_keysym_name_migrated_to_raw_char_on_load(self, tmp_path):
        v2 = {
            "version": 2,
            "ttr": [
                {"name": "Default", "forward": "w", "reverse": "s",
                 "left": "a", "right": "d", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L",
                 "action": "backslash"},
            ],
            "cc": [{"name": "Default"}],
        }
        mgr, path = _make_manager_with_file(tmp_path, v2)
        assert mgr.get_default("ttr")["action"] == "\\"
        saved = json.loads(path.read_text())
        assert saved["ttr"][0]["action"] == "\\"

    def test_raw_char_backslash_not_double_migrated(self, tmp_path):
        v2 = {
            "version": 2,
            "ttr": [
                {"name": "Default", "forward": "w", "reverse": "s",
                 "left": "a", "right": "d", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L",
                 "action": "\\"},
            ],
            "cc": [{"name": "Default"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        assert mgr.get_default("ttr")["action"] == "\\"

    def test_unrelated_actions_not_affected_by_migration(self, tmp_path):
        v2 = {
            "version": 2,
            "ttr": [
                {"name": "Default", "forward": "w", "reverse": "s",
                 "left": "a", "right": "d", "jump": "space",
                 "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L",
                 "action": "Delete"},
            ],
            "cc": [{"name": "Default"}],
        }
        mgr, _ = _make_manager_with_file(tmp_path, v2)
        assert mgr.get_default("ttr")["action"] == "Delete"
