"""LaunchTab wiring for the emblem launch menu: record on launch, build the menu
model, report running-state. Builds a real LaunchTab with a fake credentials
manager + fake settings (the established pattern - no real keyring).

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \\
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \\
      ./venv/bin/python -m pytest tests/test_launch_tab_recent_menu.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_keyring_probe(monkeypatch):
    # LaunchTab.__init__ spawns a keyring-probe QThread (and its completion path
    # calls several CredentialsManager methods). These unit tests exercise the
    # recent-menu wiring, not the probe, so stub it out: no background thread =
    # deterministic, no thread-teardown races.
    from tabs.launch_tab import LaunchTab
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)


def _acct(aid, game, label="", username="u", password="pw", token=""):
    return SimpleNamespace(id=aid, game=game, label=label, username=username,
                           password=password, launcher_token=token)


class _Cred:
    def __init__(self, accounts, keyring=True):
        self._a = accounts
        self.keyring_available = keyring
        self.keyring_probe_pending = False
        self.reads = 0                 # counts per-account credential reads
    def get_accounts_metadata(self, game=None):
        return list(self._a)
    def get_account_metadata(self, idx):
        self.reads += 1
        a = self._a[idx]
        return SimpleNamespace(id=a.id, game=a.game, label=a.label,
                               username=a.username, launcher_token=a.launcher_token)
    def get_account(self, idx):
        self.reads += 1
        return self._a[idx]
    def count(self):
        return len(self._a)


class _Store:
    def __init__(self, ids):
        self._ids = list(ids)
    def ordered_ids(self):
        return list(self._ids)
    def record(self, aid):
        self._ids = [x for x in self._ids if x != aid]
        self._ids.insert(0, aid)


def _tab(qapp, accounts, ordered, keyring=True):
    from tabs.launch_tab import LaunchTab
    sm = SimpleNamespace(get=lambda k, d=None: d, set=lambda k, v: None)
    tab = LaunchTab(cred_manager=_Cred(accounts, keyring=keyring), settings_manager=sm)
    tab._recent_launches = _Store(ordered)
    return tab


def test_is_account_running(qapp):
    tab = _tab(qapp, [_acct("a", "ttr")], ordered=["a"])
    assert tab.is_account_running("ttr", "a") is False
    tab._slots["ttr"]["a"] = SimpleNamespace(
        launcher=SimpleNamespace(is_running=lambda: True))
    assert tab.is_account_running("ttr", "a") is True
    assert tab.is_account_running("ttr", "nope") is False


def test_overlay_active_provider_defaults_false(qapp):
    tab = _tab(qapp, [_acct("a", "ttr")], ordered=["a"])
    assert tab._overlay_active() is False
    tab.set_overlay_active_provider(lambda: True)
    assert tab._overlay_active() is True


class _ToonStore:
    """Minimal RecentToonsStore double: maps account_id -> ToonRecord-like."""
    def __init__(self, by_id):
        self._by_id = dict(by_id)
    def get(self, aid):
        return self._by_id.get(aid)


def test_account_ring_includes_running(qapp):
    # Unlike the flat menu (which skips running accounts), the ring keeps them.
    tab = _tab(qapp, [_acct("a", "ttr"), _acct("b", "ttr")], ordered=["a", "b"])
    tab._slots["ttr"]["a"] = SimpleNamespace(
        launcher=SimpleNamespace(is_running=lambda: True))
    ring = tab.recent_account_ring_model()
    by_id = {r.account_id: r for r in ring}
    assert set(by_id) == {"a", "b"}            # running "a" is NOT dropped
    assert by_id["a"].running is True
    assert by_id["b"].running is False


def test_account_ring_attaches_toon_and_placeholder(qapp):
    tab = _tab(qapp, [_acct("a", "ttr"), _acct("b", "ttr")], ordered=["a", "b"])
    tab._recent_toons = _ToonStore({
        "a": SimpleNamespace(toon_name="Floss", dna="dnaA"),
    })
    by_id = {r.account_id: r for r in tab.recent_account_ring_model()}
    assert by_id["a"].toon_name == "Floss" and by_id["a"].dna == "dnaA"
    assert by_id["a"].is_placeholder is False
    assert by_id["b"].toon_name is None and by_id["b"].is_placeholder is True


def test_account_ring_keyring_locked_is_empty_no_reads(qapp):
    tab = _tab(qapp, [_acct("a", "ttr"), _acct("b", "cc")], ordered=["a", "b"],
               keyring=False)
    tab.cred_manager.reads = 0
    assert tab.recent_account_ring_model() == []   # locked -> empty ring
    assert tab.cred_manager.reads == 0             # no per-account credential reads


def test_account_ring_respects_limit(qapp):
    accts = [_acct(c, "ttr") for c in "abcde"]
    tab = _tab(qapp, accts, ordered=list("abcde"))
    assert len(tab.recent_account_ring_model(limit=2)) == 2


def test_game_of_account(qapp):
    tab = _tab(qapp, [_acct("a", "ttr"), _acct("b", "cc", token="tok")],
               ordered=["a", "b"])
    assert tab.game_of_account("a") == "ttr"
    assert tab.game_of_account("b") == "cc"
    assert tab.game_of_account("missing") is None


def test_records_launch_in_on_game_launched(qapp, monkeypatch):
    # The record call must run after the stale guard and before any early return.
    tab = _tab(qapp, [_acct("a", "ttr")], ordered=[])
    monkeypatch.setattr(tab, "_update_status", lambda *a, **k: None)
    monkeypatch.setattr(tab, "log", lambda *a, **k: None)
    launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["a"] = SimpleNamespace(launcher=launcher)
    tab._on_game_launched("ttr", "a", launcher, 1234)   # window_manager is None -> early return after record
    assert tab._recent_launches.ordered_ids() == ["a"]
