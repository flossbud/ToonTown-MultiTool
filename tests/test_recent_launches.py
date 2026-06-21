"""MRU store + menu-model logic for the emblem right-click launch menu.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      ./venv/bin/python -m pytest tests/test_recent_launches.py -q
"""
from types import SimpleNamespace
from utils.recent_launches import (
    RecentLaunchesStore, MenuItem, RecentMenuModel,
    resolve_account_view, build_recent_menu_model,
)


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


# --- menu-model logic (Task 2) ---


def _acct(aid, game, label="", username="u", password="pw", token=""):
    return SimpleNamespace(id=aid, game=game, label=label, username=username,
                           password=password, launcher_token=token)


class _Cred:
    """Index-based credentials fake matching the CredentialsManager surface
    used by resolve_account_view. Counts get_account() password reads."""
    def __init__(self, accounts):
        self._a = accounts
        self.password_reads = 0
    def get_account_metadata(self, idx):
        a = self._a[idx]
        return SimpleNamespace(id=a.id, game=a.game, label=a.label,
                               username=a.username, launcher_token=a.launcher_token)
    def get_account(self, idx):
        self.password_reads += 1
        return self._a[idx]


def _resolve(cred, i):
    # The caller fetches metadata once and passes it in; mirror that here.
    return resolve_account_view(cred, i, cred.get_account_metadata(i))


def test_resolve_ttr_launchable_with_password():
    cred = _Cred([_acct("a", "ttr", password="pw")])
    assert _resolve(cred, 0) == ("ttr", "u", True)


def test_resolve_ttr_unlaunchable_without_password():
    cred = _Cred([_acct("a", "ttr", password="")])
    assert _resolve(cred, 0) == ("ttr", "u", False)


def test_resolve_cc_token_is_launchable_without_password_read():
    cred = _Cred([_acct("c", "cc", password="", token="tok")])
    assert _resolve(cred, 0) == ("cc", "u", True)
    assert cred.password_reads == 0          # token short-circuits the read


def test_resolve_cc_falls_back_to_password_when_no_token():
    cred = _Cred([_acct("c", "cc", password="pw", token="")])
    assert _resolve(cred, 0) == ("cc", "u", True)
    assert cred.password_reads == 1


def test_resolve_prefers_label_over_username():
    cred = _Cred([_acct("a", "ttr", label="Flossbud", username="floss123")])
    assert _resolve(cred, 0)[1] == "Flossbud"


def test_resolve_none_when_no_username():
    cred = _Cred([_acct("a", "ttr", username="")])
    assert _resolve(cred, 0) is None


def test_resolve_none_when_meta_is_none():
    # A stale/deleted id resolves to no metadata; resolve must skip it without
    # touching the password.
    class _NoPw:
        def get_account(self, idx):
            raise AssertionError("should not be called")
    assert resolve_account_view(_NoPw(), 0, None) is None


def _model(ordered, views, running=(), keyring=True, count=None):
    """views: {aid: (game, label, launchable) | None}. running: set of aids."""
    if count is None:
        count = len(views)
    return build_recent_menu_model(
        ordered,
        account_for=lambda aid: views.get(aid),
        is_running=lambda game, aid: aid in running,
        keyring_available=keyring,
        account_count=count,
    )


def test_build_keeps_order_and_caps_at_four():
    views = {a: ("ttr", a, True) for a in ["a", "b", "c", "d", "e"]}
    m = _model(["a", "b", "c", "d", "e"], views)
    assert m.status == "ok"
    assert [it.account_id for it in m.items] == ["a", "b", "c", "d"]


def test_build_skips_running_deleted_and_unlaunchable():
    views = {"a": ("ttr", "a", True), "b": None,          # deleted
             "c": ("ttr", "c", False),                    # unlaunchable
             "d": ("cc", "d", True)}
    m = _model(["a", "b", "c", "d"], views, running={"a"})  # a is running
    assert [it.account_id for it in m.items] == ["d"]


def test_build_stops_reading_after_four_survivors():
    reads = []
    def account_for(aid):
        reads.append(aid)
        return ("ttr", aid, True)
    m = build_recent_menu_model(
        ["a", "b", "c", "d", "e", "f"], account_for,
        is_running=lambda g, a: False, keyring_available=True, account_count=6)
    assert len(m.items) == 4
    assert reads == ["a", "b", "c", "d"]     # never resolved e/f


def test_build_mixed_games_flag():
    mixed = _model(["a", "b"], {"a": ("ttr", "a", True), "b": ("cc", "b", True)})
    assert mixed.mixed_games is True
    same = _model(["a", "b"], {"a": ("ttr", "a", True), "b": ("ttr", "b", True)})
    assert same.mixed_games is False


def test_build_empty_status_when_no_survivors():
    m = _model(["a"], {"a": ("ttr", "a", False)})
    assert m.status == "empty"
    assert m.items == ()


def test_build_keyring_locked_short_circuits_without_reads():
    reads = []
    m = build_recent_menu_model(
        ["a", "b"], account_for=lambda aid: reads.append(aid) or ("ttr", aid, True),
        is_running=lambda g, a: False, keyring_available=False, account_count=3)
    assert m.status == "keyring_locked"
    assert m.items == ()
    assert reads == []                        # zero per-account reads


def test_build_no_accounts_is_empty_not_locked():
    m = build_recent_menu_model(
        [], account_for=lambda aid: None,
        is_running=lambda g, a: False, keyring_available=False, account_count=0)
    assert m.status == "empty"               # locked needs count > 0
