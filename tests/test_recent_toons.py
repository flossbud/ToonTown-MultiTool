from utils.recent_toons import RecentToonsStore, ToonRecord


class _FakeSettings:
    def __init__(self): self.d = {}; self.set_calls = 0
    def get(self, k, default=None): return self.d.get(k, default)
    def set(self, k, v): self.set_calls += 1; self.d[k] = v


def test_record_and_get_roundtrip():
    sm = _FakeSettings()
    store = RecentToonsStore(sm)
    assert store.get("acct-1") is None
    store.record("acct-1", "Sir Hopper", "ttr", dna="dna-string")
    rec = store.get("acct-1")
    assert rec == ToonRecord("Sir Hopper", "ttr", "dna-string")
    assert "recent_toons" in sm.d
    assert sm.d["recent_toons"]["accounts"]["acct-1"]["toons"][0]["game"] == "ttr"


def test_record_overwrites_with_latest_toon():
    store = RecentToonsStore(_FakeSettings())
    store.record("a", "Old", "ttr")
    store.record("a", "New", "ttr", dna="x")
    assert store.get("a") == ToonRecord("New", "ttr", "x")


def test_record_rejects_bad_input():
    sm = _FakeSettings()
    store = RecentToonsStore(sm)
    store.record("", "Toon", "ttr")
    store.record("a", "", "ttr")
    store.record("a", "Toon", "wat")
    assert sm.d.get("recent_toons", {}) == {}


def test_none_settings_manager_degrades_to_empty():
    store = RecentToonsStore(None)
    store.record("a", "Toon", "ttr")
    assert store.get("a") is None


def test_get_tolerates_corrupt_entry():
    sm = _FakeSettings()
    sm.d["recent_toons"] = {"a": {"toon_name": "", "game": "ttr"}, "b": "notadict"}
    store = RecentToonsStore(sm)
    assert store.get("a") is None
    assert store.get("b") is None


def test_record_skips_write_when_unchanged():
    sm = _FakeSettings()
    store = RecentToonsStore(sm)
    store.record("a", "Toon", "ttr", "d")
    assert sm.set_calls == 1
    # Identical data -> dirty-check short-circuits before the settings write.
    store.record("a", "Toon", "ttr", "d")
    assert sm.set_calls == 1
    # Changed data -> writes again.
    store.record("a", "Toon", "ttr", "d2")
    assert sm.set_calls == 2


class _FakeSM:
    def __init__(self, data=None): self.data = dict(data or {})
    def get(self, k, d=None): return self.data.get(k, d)
    def set(self, k, v): self.data[k] = v


def test_record_appends_a_list_most_recent_first():
    s = RecentToonsStore(_FakeSM())
    s.record("a", "Moe", "ttr", "dna1", laff=120, max_laff=137, species="DOG", accent="#4a8fe7")
    s.record("a", "Zed", "ttr", "dna2", laff=60, max_laff=60, species="CAT", accent="#e05252")
    names = [r.toon_name for r in s.list("a")]
    assert names == ["Zed", "Moe"]
    assert s.list("a")[0].species == "CAT"

def test_record_dedups_and_moves_to_front():
    s = RecentToonsStore(_FakeSM())
    s.record("a", "Moe", "ttr", "dna1")
    s.record("a", "Zed", "ttr", "dna2")
    s.record("a", "Moe", "ttr", "dna1", laff=99, max_laff=99)
    names = [r.toon_name for r in s.list("a")]
    assert names == ["Moe", "Zed"]
    assert s.list("a")[0].laff == 99

def test_get_resolves_primary_then_most_recent():
    s = RecentToonsStore(_FakeSM())
    s.record("a", "Moe", "ttr", "dna1")
    s.record("a", "Zed", "ttr", "dna2")
    assert s.get("a").toon_name == "Zed"
    s.set_primary("a", "Moe")
    assert s.get("a").toon_name == "Moe"
    assert s.primary_name("a") == "Moe"

def test_set_primary_ignores_unknown_toon():
    s = RecentToonsStore(_FakeSM())
    s.record("a", "Moe", "ttr", "dna1")
    s.set_primary("a", "Ghost")
    assert s.primary_name("a") is None

def test_cap_at_8():
    s = RecentToonsStore(_FakeSM())
    for i in range(10):
        s.record("a", f"T{i}", "ttr", f"dna{i}")
    assert len(s.list("a")) == 8
    assert s.list("a")[0].toon_name == "T9"

def test_v1_flat_shape_migrates_on_read():
    sm = _FakeSM({"recent_toons": {
        "a": {"toon_name": "Moe", "game": "ttr",
              "dna": "74090202015f1b541b361b080008080104002a00000e0000000000120000012b00"}}})
    s = RecentToonsStore(sm)
    rec = s.get("a")
    assert rec.toon_name == "Moe"
    assert rec.species is not None      # backfilled from DNA (HORSE)
    assert sm.data["recent_toons"]["_v"] == 2
    assert sm.data["recent_toons"]["accounts"]["a"]["toons"][0]["toon_name"] == "Moe"

def test_none_sm_is_noop():
    s = RecentToonsStore(None)
    s.record("a", "Moe", "ttr", "dna1")
    assert s.list("a") == [] and s.get("a") is None
