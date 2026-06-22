from utils.recent_toons import RecentToonsStore, ToonRecord


class _FakeSettings:
    def __init__(self): self.d = {}
    def get(self, k, default=None): return self.d.get(k, default)
    def set(self, k, v): self.d[k] = v


def test_record_and_get_roundtrip():
    sm = _FakeSettings()
    store = RecentToonsStore(sm)
    assert store.get("acct-1") is None
    store.record("acct-1", "Sir Hopper", "ttr", dna="dna-string")
    rec = store.get("acct-1")
    assert rec == ToonRecord("Sir Hopper", "ttr", "dna-string")
    assert "recent_toons" in sm.d and sm.d["recent_toons"]["acct-1"]["game"] == "ttr"


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
