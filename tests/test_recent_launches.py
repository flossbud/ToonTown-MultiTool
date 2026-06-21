"""MRU store + menu-model logic for the emblem right-click launch menu.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      ./venv/bin/python -m pytest tests/test_recent_launches.py -q
"""
from utils.recent_launches import RecentLaunchesStore


class _DictSettings:
    """Minimal settings_manager stand-in: dict-backed get/set."""
    def __init__(self):
        self.data = {}
    def get(self, key, default=None):
        return self.data.get(key, default)
    def set(self, key, value):
        self.data[key] = value


def test_record_inserts_at_front():
    s = RecentLaunchesStore(_DictSettings())
    s.record("a")
    s.record("b")
    assert s.ordered_ids() == ["b", "a"]


def test_record_dedups_moving_to_front():
    s = RecentLaunchesStore(_DictSettings())
    s.record("a")
    s.record("b")
    s.record("a")
    assert s.ordered_ids() == ["a", "b"]


def test_record_truncates_to_cap_of_ten():
    s = RecentLaunchesStore(_DictSettings())
    for i in range(13):
        s.record(f"id{i}")
    # Exactly the 10 most-recent, newest-first (id12..id3); id0/id1/id2 dropped.
    assert s.ordered_ids() == [f"id{i}" for i in range(12, 2, -1)]


def test_record_ignores_empty_id():
    s = RecentLaunchesStore(_DictSettings())
    s.record("")
    s.record(None)
    assert s.ordered_ids() == []


def test_ordered_ids_tolerates_malformed_storage():
    sm = _DictSettings()
    sm.data["recent_launches"] = ["ok", 5, None, {"x": 1}, "ok2"]
    s = RecentLaunchesStore(sm)
    assert s.ordered_ids() == ["ok", "ok2"]   # non-strings dropped


def test_ordered_ids_when_unset_is_empty():
    assert RecentLaunchesStore(_DictSettings()).ordered_ids() == []


def test_none_settings_manager_is_noop():
    s = RecentLaunchesStore(None)
    s.record("a")                    # must not raise
    assert s.ordered_ids() == []     # no persistence, always empty


def test_round_trip_persists_via_real_settings_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.settings_manager import SettingsManager
    s1 = RecentLaunchesStore(SettingsManager())
    s1.record("a")
    s1.record("b")
    # A fresh store over a fresh SettingsManager (same config dir) sees the data.
    s2 = RecentLaunchesStore(SettingsManager())
    assert s2.ordered_ids() == ["b", "a"]
