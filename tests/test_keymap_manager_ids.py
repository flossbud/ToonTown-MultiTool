"""KeymapManager: stable set ids, hidden sets and reordering."""

import json
import os

from utils.keymap_manager import KeymapManager


def _make(tmp_path, contents=None):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    path = cfg / "keymaps.json"
    if contents is not None:
        path.write_text(json.dumps(contents))
    os.environ["TTMT_CONFIG_DIR"] = str(cfg)
    try:
        mgr = KeymapManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)
    return mgr, path


def _reload(path):
    os.environ["TTMT_CONFIG_DIR"] = str(path.parent)
    try:
        return KeymapManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)


def _ttr_set(name, **keys):
    base = {"name": name, "forward": "w", "reverse": "s", "left": "a",
            "right": "d", "jump": "Control_L", "book": "Escape", "gags": "Home",
            "tasks": "End", "map": "Alt_L", "action": "Delete"}
    base.update(keys)
    return base


def _v2(ttr, cc=None):
    return {"version": 2, "ttr": ttr, "cc": cc or []}


class TestIdsOnLoad:
    def test_fresh_file_sets_have_ids(self, tmp_path):
        mgr, path = _make(tmp_path)
        data = json.loads(path.read_text())
        for game in ("ttr", "cc"):
            assert isinstance(data[game][0]["id"], str) and data[game][0]["id"]
        assert mgr.get_set_ids("ttr") == [data["ttr"][0]["id"]]

    def test_old_file_gets_ids_and_is_otherwise_unchanged(self, tmp_path):
        old = _v2([_ttr_set("Default"), _ttr_set("Arrows", forward="Up")])
        mgr, path = _make(tmp_path, old)
        data = json.loads(path.read_text())
        ids = [s["id"] for s in data["ttr"] + data["cc"]]
        assert len(set(ids)) == len(ids)
        for before, after in zip(old["ttr"], data["ttr"]):
            stripped = {k: v for k, v in after.items() if k != "id"}
            assert stripped == before
        assert "hidden" not in data["ttr"][0]
        assert "hidden" not in data["ttr"][1]

    def test_ids_survive_reload(self, tmp_path):
        mgr, path = _make(tmp_path, _v2([_ttr_set("Default"), _ttr_set("B")]))
        ids = mgr.get_set_ids("ttr")
        assert _reload(path).get_set_ids("ttr") == ids

    def test_existing_ids_are_kept(self, tmp_path):
        mgr, path = _make(tmp_path, _v2([
            {**_ttr_set("Default"), "id": "base0001"},
            {**_ttr_set("B"), "id": "bbbb0002"},
        ]))
        assert mgr.get_set_ids("ttr") == ["base0001", "bbbb0002"]

    def test_duplicate_and_bad_ids_are_replaced(self, tmp_path):
        mgr, path = _make(tmp_path, _v2([
            {**_ttr_set("Default"), "id": "same"},
            {**_ttr_set("B"), "id": "same"},
            {**_ttr_set("C"), "id": 7},
            {**_ttr_set("D"), "id": ""},
        ]))
        ids = mgr.get_set_ids("ttr")
        assert ids[0] == "same"
        assert len(set(ids)) == 4
        assert all(isinstance(i, str) and i for i in ids)
        assert json.loads(path.read_text())["ttr"][1]["id"] == ids[1]

    def test_ids_unique_across_games(self, tmp_path):
        mgr, _ = _make(tmp_path, {"version": 2,
                                  "ttr": [{**_ttr_set("Default"), "id": "x1"}],
                                  "cc": [{"name": "Default", "id": "x1"}]})
        assert mgr.get_set_ids("ttr") == ["x1"]
        assert mgr.get_set_ids("cc")[0] != "x1"

    def test_v1_migration_assigns_ids(self, tmp_path):
        mgr, path = _make(tmp_path, [{"name": "Default", "up": "w", "down": "s"}])
        data = json.loads(path.read_text())
        assert data["ttr"][0]["id"] and data["cc"][0]["id"]


class TestLookup:
    def test_get_set_by_id_and_index_of(self, tmp_path):
        mgr, _ = _make(tmp_path)
        sid = mgr.add_set("ttr", name="Arrows")
        assert mgr.index_of("ttr", sid) == 1
        assert mgr.id_at("ttr", 1) == sid
        assert mgr.get_set_by_id("ttr", sid)["name"] == "Arrows"
        assert mgr.get_set_by_id("cc", sid) is None
        assert mgr.index_of("ttr", "nope") == -1
        assert mgr.id_at("ttr", 5) is None

    def test_add_set_returns_none_when_full(self, tmp_path):
        mgr, _ = _make(tmp_path)
        for _ in range(KeymapManager.MAX_SETS_PER_GAME - 1):
            assert mgr.add_set("ttr") is not None
        assert mgr.add_set("ttr") is None
        assert mgr.add_set("nope") is None

    def test_rename_keeps_id(self, tmp_path):
        mgr, _ = _make(tmp_path)
        sid = mgr.add_set("ttr")
        mgr.update_set_name("ttr", 1, "Renamed")
        assert mgr.id_at("ttr", 1) == sid


class TestHidden:
    def test_hide_and_show(self, tmp_path):
        mgr, path = _make(tmp_path)
        sid = mgr.add_set("ttr")
        assert mgr.set_hidden("ttr", sid, True) is True
        assert mgr.is_hidden("ttr", sid)
        assert json.loads(path.read_text())["ttr"][1]["hidden"] is True
        assert [s["id"] for s in mgr.visible_sets("ttr")] == [mgr.id_at("ttr", 0)]
        assert mgr.set_hidden("ttr", sid, False) is True
        assert not mgr.is_hidden("ttr", sid)
        assert "hidden" not in json.loads(path.read_text())["ttr"][1]

    def test_set_zero_may_be_hidden(self, tmp_path):
        mgr, _ = _make(tmp_path)
        base = mgr.id_at("ttr", 0)
        sid = mgr.add_set("ttr")
        assert mgr.set_hidden("ttr", base, True) is True
        assert mgr.lowest_visible_id("ttr") == sid

    def test_refuses_to_hide_last_visible(self, tmp_path):
        mgr, _ = _make(tmp_path)
        base = mgr.id_at("ttr", 0)
        assert mgr.set_hidden("ttr", base, True) is False
        assert not mgr.is_hidden("ttr", base)
        sid = mgr.add_set("ttr")
        assert mgr.set_hidden("ttr", base, True) is True
        assert mgr.set_hidden("ttr", sid, False) is True     # already shown
        assert mgr.set_hidden("ttr", sid, True) is False     # last visible

    def test_unknown_id_or_game(self, tmp_path):
        mgr, _ = _make(tmp_path)
        assert mgr.set_hidden("ttr", "nope", True) is False
        assert mgr.set_hidden("nope", mgr.id_at("ttr", 0), True) is False

    def test_lowest_visible_id(self, tmp_path):
        mgr, _ = _make(tmp_path)
        base = mgr.id_at("ttr", 0)
        a = mgr.add_set("ttr")
        b = mgr.add_set("ttr")
        assert mgr.lowest_visible_id("ttr") == base
        mgr.set_hidden("ttr", base, True)
        mgr.set_hidden("ttr", a, True)
        assert mgr.lowest_visible_id("ttr") == b

    def test_hidden_per_game(self, tmp_path):
        mgr, _ = _make(tmp_path)
        mgr.add_set("ttr")
        mgr.set_hidden("ttr", mgr.id_at("ttr", 0), True)
        assert not mgr.is_hidden("cc", mgr.id_at("cc", 0))

    def test_hidden_survives_reload(self, tmp_path):
        mgr, path = _make(tmp_path)
        sid = mgr.add_set("ttr")
        mgr.set_hidden("ttr", sid, True)
        assert _reload(path).is_hidden("ttr", sid)

    def test_all_hidden_file_shows_set_zero(self, tmp_path):
        mgr, path = _make(tmp_path, _v2([
            {**_ttr_set("Default"), "id": "a", "hidden": True},
            {**_ttr_set("B"), "id": "b", "hidden": True},
        ]))
        assert not mgr.is_hidden("ttr", "a")
        assert mgr.is_hidden("ttr", "b")
        assert "hidden" not in json.loads(path.read_text())["ttr"][0]

    def test_non_true_hidden_values_are_dropped(self, tmp_path):
        mgr, path = _make(tmp_path, _v2([
            {**_ttr_set("Default"), "id": "a"},
            {**_ttr_set("B"), "id": "b", "hidden": False},
            {**_ttr_set("C"), "id": "c", "hidden": "yes"},
        ]))
        assert not mgr.is_hidden("ttr", "b")
        assert not mgr.is_hidden("ttr", "c")
        data = json.loads(path.read_text())
        assert all("hidden" not in s for s in data["ttr"])

    def test_deleting_last_visible_shows_set_zero(self, tmp_path):
        mgr, _ = _make(tmp_path)
        base = mgr.id_at("ttr", 0)
        sid = mgr.add_set("ttr")
        mgr.set_hidden("ttr", base, True)
        mgr.delete_set("ttr", mgr.index_of("ttr", sid))
        assert not mgr.is_hidden("ttr", base)
        assert mgr.lowest_visible_id("ttr") == base

    def test_hide_notifies_once_and_noop_does_not(self, tmp_path):
        mgr, _ = _make(tmp_path)
        sid = mgr.add_set("ttr")
        calls = []
        mgr.on_change(lambda: calls.append(1))
        mgr.set_hidden("ttr", sid, True)
        assert calls == [1]
        mgr.set_hidden("ttr", sid, True)
        mgr.set_hidden("ttr", mgr.id_at("ttr", 0), True)   # refused
        assert calls == [1]


class TestMoveSet:
    def _three(self, tmp_path):
        mgr, path = _make(tmp_path)
        a = mgr.add_set("ttr", name="A")
        b = mgr.add_set("ttr", name="B")
        c = mgr.add_set("ttr", name="C")
        return mgr, path, mgr.id_at("ttr", 0), a, b, c

    def test_move_down_and_up(self, tmp_path):
        mgr, path, base, a, b, c = self._three(tmp_path)
        assert mgr.move_set("ttr", a, 3) is True
        assert mgr.get_set_ids("ttr") == [base, b, c, a]
        assert mgr.move_set("ttr", a, 1) is True
        assert mgr.get_set_ids("ttr") == [base, a, b, c]
        assert _reload(path).get_set_ids("ttr") == [base, a, b, c]

    def test_bindings_travel_with_id(self, tmp_path):
        mgr, _, base, a, b, c = self._three(tmp_path)
        mgr.update_set_key("ttr", mgr.index_of("ttr", a), "forward", "i")
        mgr.move_set("ttr", a, 3)
        assert mgr.get_set_by_id("ttr", a)["forward"] == "i"
        assert mgr.get_key_for_action("ttr", 3, "forward") == "i"

    def test_set_zero_is_pinned(self, tmp_path):
        mgr, _, base, a, b, c = self._three(tmp_path)
        assert mgr.move_set("ttr", base, 2) is False
        assert mgr.move_set("ttr", a, 0) is False
        assert mgr.get_set_ids("ttr") == [base, a, b, c]

    def test_out_of_range_and_unknown(self, tmp_path):
        mgr, _, base, a, b, c = self._three(tmp_path)
        assert mgr.move_set("ttr", a, 4) is False
        assert mgr.move_set("ttr", a, -1) is False
        assert mgr.move_set("ttr", "nope", 2) is False
        assert mgr.move_set("cc", a, 1) is False
        assert mgr.get_set_ids("ttr") == [base, a, b, c]

    def test_same_index_is_noop_without_notify(self, tmp_path):
        mgr, _, base, a, b, c = self._three(tmp_path)
        calls = []
        mgr.on_change(lambda: calls.append(1))
        assert mgr.move_set("ttr", a, 1) is True
        assert calls == []
        mgr.move_set("ttr", a, 2)
        assert calls == [1]

    def test_hidden_flag_travels(self, tmp_path):
        mgr, _, base, a, b, c = self._three(tmp_path)
        mgr.set_hidden("ttr", b, True)
        mgr.move_set("ttr", b, 3)
        assert mgr.is_hidden("ttr", b)
        assert [s["id"] for s in mgr.visible_sets("ttr")] == [base, a, c]


class TestIndexAddressedCallersStillWork:
    def test_delete_set_by_index_keeps_other_ids(self, tmp_path):
        mgr, _ = _make(tmp_path)
        base = mgr.id_at("ttr", 0)
        a = mgr.add_set("ttr")
        b = mgr.add_set("ttr")
        mgr.delete_set("ttr", 1)
        assert mgr.get_set_ids("ttr") == [base, b]
        assert mgr.index_of("ttr", a) == -1
        mgr.delete_set("ttr", 0)        # still protected
        assert mgr.get_set_ids("ttr") == [base, b]

    def test_set_names_unchanged_by_ids(self, tmp_path):
        mgr, _ = _make(tmp_path)
        mgr.add_set("ttr", name="Arrows")
        assert mgr.get_set_names("ttr") == ["Default", "Arrows"]

    def test_get_action_in_set_ignores_id_and_hidden(self, tmp_path):
        mgr, _ = _make(tmp_path)
        sid = mgr.add_set("ttr", keys={"forward": "i"})
        mgr.set_hidden("ttr", sid, True)
        assert mgr.get_action_in_set("ttr", 1, "i") == "forward"
        assert mgr.get_action_in_set("ttr", 1, sid) is None
        assert sid not in mgr.get_keys_for_game("ttr")
