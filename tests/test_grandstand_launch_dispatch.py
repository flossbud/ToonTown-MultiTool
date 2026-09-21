"""Play dispatches the party: ordered, staggered, skipping live sessions."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from tabs.launch_tab import PARTY_STAGGER_MS


class FakeTab:
    """The dispatch logic under test, isolated from Qt and login workers."""

    def __init__(self, running=(), inflight=()):
        from tabs.launch_tab import LaunchTab
        self.launched = []
        self._running = set(running)
        self._inflight = set(inflight)
        self._party_pending = set()
        self._party_dispatch_targets = \
            LaunchTab._party_dispatch_targets.__get__(self)
        self.is_account_running = lambda g, a: a in self._running
        self._is_in_flight = lambda g, a: a in self._inflight


def test_stagger_is_400ms(qapp):
    """Spec §6: the interval is what makes 'the star launches first' real."""
    import tabs.launch_tab as lt

    launched = []
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._on_launch = lambda game, account_id: launched.append(account_id)

    lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b", "c", "d"])

    assert PARTY_STAGGER_MS == 400
    assert launched == ["a"]
    assert [timer.interval() for timer in tab._party_timers] == [400, 800, 1200]
    for timer in tab._party_timers:
        timer.stop()
        timer.deleteLater()


def test_targets_preserve_the_given_order():
    tab = FakeTab()
    assert tab._party_dispatch_targets("ttr", ["c", "a", "b"]) == ["c", "a", "b"]


def test_running_accounts_are_skipped():
    """Spec §6: a running account may be checked; Play must not relaunch it."""
    tab = FakeTab(running={"b"})
    assert tab._party_dispatch_targets("ttr", ["a", "b", "c"]) == ["a", "c"]


def test_in_flight_accounts_are_skipped():
    tab = FakeTab(inflight={"a"})
    assert tab._party_dispatch_targets("ttr", ["a", "b"]) == ["b"]


@pytest.mark.parametrize("state", [
    "logging_in", "launching", "loading", "queued", "need_2fa",
])
def test_real_in_flight_mapping_covers_every_launch_state(state):
    from tabs.launch_tab import LaunchTab

    slot = object()
    tab = SimpleNamespace(
        _slots={"ttr": {"a": slot}},
        _effective_state=lambda game, current: (state, "", ""),
    )

    assert LaunchTab._is_in_flight(tab, "ttr", "a") is True


def test_an_entirely_live_party_dispatches_nothing():
    tab = FakeTab(running={"a", "b"})
    assert tab._party_dispatch_targets("ttr", ["a", "b"]) == []


def test_empty_order_is_safe():
    assert FakeTab()._party_dispatch_targets("ttr", []) == []


def test_party_refilters_targets_after_cc_gate(monkeypatch, qapp):
    """The gate runs a nested loop, so its pre-dialog targets may be stale."""
    import tabs.launch_tab as lt

    running = set()
    launched = []

    def gate(settings_manager, parent):
        running.add("a")
        return True

    monkeypatch.setattr(lt, "_cc_launch_gate", gate)
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: account_id in running
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._on_launch = lambda game, account_id: launched.append(account_id)

    lt.LaunchTab._on_party_launch(tab, "cc", ["a", "b"])

    assert launched == ["b"]
    assert tab._party_timers == []


def test_shutdown_during_cc_gate_dispatches_nothing(monkeypatch, qapp):
    """A gate returning after teardown must not revive party dispatch."""
    import tabs.launch_tab as lt

    launched = []
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._slots = {"ttr": {}, "cc": {}}
    tab._loading = {"ttr": [], "cc": []}
    tab._probe_thread = None
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._on_launch = lambda game, account_id: launched.append(account_id)

    def gate(settings_manager, parent):
        lt.LaunchTab.shutdown(tab)
        return True

    monkeypatch.setattr(lt, "_cc_launch_gate", gate)

    lt.LaunchTab._on_party_launch(tab, "cc", ["a", "b"])

    try:
        assert launched == []
        assert tab._party_timers == []
        assert not any(timer.isActive() for timer in tab._party_timers)
    finally:
        for timer in tab._party_timers:
            timer.stop()
            timer.deleteLater()


def test_cc_gate_is_consulted_once_per_batch(monkeypatch, qapp, tmp_path):
    """Spec §6: a four-toon Clash launch asks once, not four times.

    `_on_party_launch` gates the batch, then `_on_launch` gates each account.
    Without suppression that is 1 + N prompts. This exercises both production
    gate sites; only work downstream of `_on_launch`'s gate is stubbed.
    """
    import tabs.launch_tab as lt

    account_ids = ["a", "b", "c", "d"]
    calls = []
    launched = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])
    engine_dir = tmp_path / "cc"
    engine_dir.mkdir()
    (engine_dir / lt.get_cc_engine_executable_name()).touch()

    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda g, a: False
    tab._is_in_flight = lambda g, a: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)
    tab._on_launch = lt.LaunchTab._on_launch.__get__(tab)
    tab._global_index_of = lt.LaunchTab._global_index_of.__get__(tab)
    tab._slots = {
        "ttr": {},
        "cc": {aid: SimpleNamespace(worker=None, launcher=None)
               for aid in account_ids},
    }
    accounts = [SimpleNamespace(
        id=aid, username=aid, password="", launcher_token=f"token-{aid}",
        label=aid) for aid in account_ids]
    tab.cred_manager = SimpleNamespace(
        keyring_probe_pending=False,
        keyring_available=True,
        get_accounts_metadata=lambda: accounts,
        get_account=lambda index: accounts[index],
    )
    tab._get_engine_dir = lambda game: str(engine_dir)
    tab._position_of = lambda game, aid: account_ids.index(aid) + 1
    tab._update_status = lambda *args: None
    tab._show_failure_dialog = lambda *args: None
    tab.log = lambda message: None

    def make_launchers(game, account_id):
        worker = SimpleNamespace(
            login_with_token=lambda token, aid=account_id:
                launched.append(aid))
        tab._slots[game][account_id].worker = worker
        return worker, None

    tab._make_launchers = make_launchers

    lt.LaunchTab._on_party_launch(tab, "cc", account_ids)
    QTest.qWait(PARTY_STAGGER_MS * 3 + 100)

    assert calls == [1]
    assert launched == account_ids


def test_cc_gate_stays_answered_after_first_account_fails(
        monkeypatch, qapp, tmp_path):
    """A synchronous failure must not re-prompt accounts still staggered."""
    import tabs.launch_tab as lt

    account_ids = ["a", "b", "c", "d"]
    calls = []
    attempted = []
    launched = []
    failed = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])
    engine_dir = tmp_path / "cc"
    engine_dir.mkdir()
    (engine_dir / lt.get_cc_engine_executable_name()).touch()
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)
    tab._on_launch = lt.LaunchTab._on_launch.__get__(tab)
    tab._global_index_of = lt.LaunchTab._global_index_of.__get__(tab)
    tab._slots = {
        "ttr": {},
        "cc": {aid: SimpleNamespace(worker=None, launcher=None)
               for aid in account_ids},
    }
    accounts = [
        SimpleNamespace(
            id="a", username="", password="", launcher_token="", label="a"),
        *[SimpleNamespace(
            id=aid, username=aid, password="", launcher_token=f"token-{aid}",
            label=aid) for aid in account_ids[1:]],
    ]

    def get_account(index):
        attempted.append(account_ids[index])
        return accounts[index]

    tab.cred_manager = SimpleNamespace(
        keyring_probe_pending=False,
        keyring_available=True,
        get_accounts_metadata=lambda: accounts,
        get_account=get_account,
    )
    tab._get_engine_dir = lambda game: str(engine_dir)
    tab._position_of = lambda game, aid: account_ids.index(aid) + 1
    tab._update_status = lambda *args: None
    tab._show_failure_dialog = \
        lambda game, aid, message: failed.append(aid)
    tab.log = lambda message: None

    def make_launchers(game, account_id):
        worker = SimpleNamespace(
            login_with_token=lambda token, aid=account_id:
                launched.append(aid))
        tab._slots[game][account_id].worker = worker
        return worker, None

    tab._make_launchers = make_launchers

    lt.LaunchTab._on_party_launch(tab, "cc", account_ids)
    QTest.qWait(PARTY_STAGGER_MS * 3 + 100)

    assert calls == [1]
    assert attempted == account_ids
    assert failed == ["a"]
    assert launched == account_ids[1:]


def test_single_card_launch_consults_the_real_gate(monkeypatch, qapp):
    """The real per-account entry point must gate a launch outside a batch."""
    import tabs.launch_tab as lt

    calls = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), False)[1])
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.cred_manager = SimpleNamespace(
        keyring_probe_pending=False, keyring_available=True)
    tab._slots = {"ttr": {}, "cc": {"a": object()}}
    tab._global_index_of = lambda account_id: 0
    tab._party_gate_ok = set()
    tab._party_pending = set()

    lt.LaunchTab._on_launch(tab, "cc", "a")

    assert calls == [1]


def test_gate_authorization_does_not_leak_during_nested_launch(
        monkeypatch, qapp):
    """A solo launch inside a party failure dialog is a separate intent."""
    import tabs.launch_tab as lt

    calls = []
    launched = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        if game == "cc" and not tab._cc_gate_ok(game, account_id):
            return
        launched.append(account_id)
        if account_id == "a":
            tab._on_launch("cc", "solo")

    tab._on_launch = fake_on_launch

    lt.LaunchTab._on_party_launch(tab, "cc", ["a"])

    assert calls == [1, 1]
    assert launched == ["a", "solo"]


def test_repeated_play_does_not_duplicate_pending_accounts(qapp):
    """Accounts waiting on the stagger are already part of a launch intent."""
    import tabs.launch_tab as lt

    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    launched = []
    inflight = set()
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: account_id in inflight
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)

    def fake_on_launch(game, account_id):
        launched.append(account_id)
        inflight.add(account_id)

    tab._on_launch = fake_on_launch

    lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b", "c"])
    lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b", "c"])
    QTest.qWait(PARTY_STAGGER_MS * 2 + 100)

    assert launched == ["a", "b", "c"]


def test_first_dispatch_exception_releases_unarmed_party(qapp):
    """A raising first launch cannot strand accounts without timers."""
    import tabs.launch_tab as lt

    launched = []
    fail_first = [True]
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)

    def fake_on_launch(game, account_id):
        if account_id == "a" and fail_first[0]:
            fail_first[0] = False
            raise RuntimeError("first launch failed")
        launched.append(account_id)

    tab._on_launch = fake_on_launch

    with pytest.raises(RuntimeError, match="first launch failed"):
        lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b", "c"])

    assert tab._party_pending == set()
    assert tab._party_timers == []

    lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b", "c"])
    QTest.qWait(PARTY_STAGGER_MS * 2 + 100)

    assert launched == ["a", "b", "c"]
    assert tab._party_pending == set()


def test_direct_launch_returns_before_lookup_for_a_pending_account():
    """A card click cannot pull a reserved account ahead of its timer."""
    import tabs.launch_tab as lt

    looked_up = []
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    tab.cred_manager = SimpleNamespace(
        keyring_probe_pending=False, keyring_available=True)
    tab._party_pending = {("ttr", "a")}
    tab._slots = {"ttr": {"a": object()}, "cc": {}}
    tab._global_index_of = lambda account_id: looked_up.append(account_id)

    lt.LaunchTab._on_launch(tab, "ttr", "a")

    assert looked_up == []


def test_single_card_gate_does_not_inherit_pending_batch(monkeypatch, qapp):
    """A separate card click is a separate user intent and gets its own gate."""
    import tabs.launch_tab as lt

    calls = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        if game == "cc" and not tab._cc_gate_ok(game, account_id):
            return

    tab._on_launch = fake_on_launch

    lt.LaunchTab._on_party_launch(tab, "cc", ["a", "b"])
    tab._on_launch("cc", "solo")

    assert calls == [1, 1]


def test_ttr_party_does_not_rearm_pending_cc_gate(monkeypatch, qapp):
    """An unrelated party cannot change the gate answer for queued CC work."""
    import tabs.launch_tab as lt

    calls = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.window = lambda: None
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        if game == "cc" and not tab._cc_gate_ok(game, account_id):
            return

    tab._on_launch = fake_on_launch

    lt.LaunchTab._on_party_launch(tab, "cc", ["a", "b"])
    lt.LaunchTab._on_party_launch(tab, "ttr", ["x"])
    QTest.qWait(PARTY_STAGGER_MS + 100)

    assert calls == [1]


def test_completed_party_timers_are_released(qapp):
    import tabs.launch_tab as lt

    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.is_account_running = lambda game, account_id: False
    tab._is_in_flight = lambda game, account_id: False
    tab._party_timers = []
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._shutting_down = False
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._on_launch = lambda game, account_id: None

    lt.LaunchTab._on_party_launch(tab, "ttr", ["a", "b"])
    QTest.qWait(PARTY_STAGGER_MS + 100)

    assert tab._party_timers == []


def test_shutdown_stops_pending_party_timers(qapp):
    """A stagger that fires after teardown would launch a game the user has
    already closed the tab on."""
    import tabs.launch_tab as lt

    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    timer = QTimer(tab)
    timer.setSingleShot(True)
    timer.start(10_000)
    tab._party_timers = [timer]
    tab._party_gate_ok = {("cc", "pending")}
    tab._party_pending = {("ttr", "pending")}
    tab._slots = {"ttr": {}, "cc": {}}
    tab._loading = {"ttr": [], "cc": []}
    tab._probe_thread = None

    lt.LaunchTab.shutdown(tab)

    assert timer.isActive() is False
    assert tab._party_timers == []
    assert tab._party_gate_ok == set()
    assert tab._party_pending == set()


def test_unflagged_running_cc_account_still_reaches_the_relaunch_branch(
        monkeypatch, qapp, tmp_path):
    """The legacy launcher (nothing mounted) keeps its base behaviour: a
    running account that passes the gate proceeds to the relaunch branch,
    which terminates the game. The flagged launcher's post-gate bail on a
    live account must not leak into this path."""
    import tabs.launch_tab as lt

    monkeypatch.setattr(lt, "_cc_launch_gate", lambda sm, parent: True)
    engine_dir = tmp_path / "cc"
    engine_dir.mkdir()
    (engine_dir / lt.get_cc_engine_executable_name()).touch()

    launcher = SimpleNamespace(is_running=lambda: True, kill=MagicMock())
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    assert not hasattr(tab, "grandstand")          # the unflagged shape
    tab.settings_manager = None
    tab.window = lambda: None
    tab._shutting_down = False
    tab._party_gate_ok = set()
    tab._party_pending = set()
    tab._slots = {"ttr": {},
                  "cc": {"a": SimpleNamespace(worker=None, launcher=launcher)}}
    tab.is_account_running = lt.LaunchTab.is_account_running.__get__(tab)
    tab._is_in_flight = lambda game, account_id: False
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)
    tab._global_index_of = lt.LaunchTab._global_index_of.__get__(tab)
    account = SimpleNamespace(id="a", username="a", password="pw",
                              launcher_token="token-a", label="a")
    tab.cred_manager = SimpleNamespace(
        keyring_probe_pending=False, keyring_available=True,
        get_accounts_metadata=lambda: [account],
        get_account=lambda index: account)
    tab._get_engine_dir = lambda game: str(engine_dir)
    tab._position_of = lambda game, aid: 1
    tab._update_status = lambda *args: None
    tab._show_failure_dialog = lambda *args: None
    tab._make_launchers = MagicMock()
    tab.log = lambda message, **kwargs: None

    lt.LaunchTab._on_launch(tab, "cc", "a")

    launcher.kill.assert_called_once_with()
    tab._make_launchers.assert_not_called()
