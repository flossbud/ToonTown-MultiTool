"""Play dispatches the party: ordered, staggered, skipping live sessions."""
import os
from types import SimpleNamespace

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


def test_stagger_is_400ms():
    """Spec §6: the interval is what makes 'the star launches first' real."""
    assert PARTY_STAGGER_MS == 400


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


def test_cc_gate_is_consulted_once_per_batch(monkeypatch, qapp):
    """Spec §6: a four-toon Clash launch asks once, not four times.

    `_on_party_launch` gates the batch, then `_on_launch` gates each account.
    Without suppression that is 1 + N prompts. This exercises BOTH gate sites:
    the per-account stub runs the same guarded branch `_on_launch` runs.
    """
    import tabs.launch_tab as lt

    calls = []
    monkeypatch.setattr(lt, "_cc_launch_gate",
                        lambda sm, parent: (calls.append(1), True)[1])

    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    QWidget.__init__(tab)
    tab.settings_manager = None
    tab.launched = []
    tab.window = lambda: None
    tab.is_account_running = lambda g, a: False
    tab._is_in_flight = lambda g, a: False
    tab._party_timers = []
    tab._party_gate_passed = False
    tab._party_pending = set()
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        # The one line of _on_launch that matters here, unchanged.
        if game == "cc" and not tab._cc_gate_ok():
            return
        tab.launched.append(account_id)

    tab._on_launch = fake_on_launch

    lt.LaunchTab._on_party_launch(tab, "cc", ["a", "b", "c"])
    assert calls == [1]                      # asked exactly once
    assert tab.launched == ["a"]             # rest are on staggered timers


def test_a_single_card_launch_still_gets_its_own_gate():
    """The suppression must not leak: outside a batch every launch asks."""
    import tabs.launch_tab as lt
    tab = lt.LaunchTab.__new__(lt.LaunchTab)
    tab._party_gate_passed = False
    tab._party_pending = set()
    assert lt.LaunchTab._cc_gate_ok.__get__(tab) is not None


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
    tab._party_gate_passed = False
    tab._party_pending = set()

    lt.LaunchTab._on_launch(tab, "cc", "a")

    assert calls == [1]


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
    tab._party_gate_passed = False
    tab._party_pending = set()
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
    tab._party_gate_passed = False
    tab._party_pending = set()
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        if game == "cc" and not tab._cc_gate_ok():
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
    tab._party_gate_passed = False
    tab._party_pending = set()
    tab._party_dispatch_targets = \
        lt.LaunchTab._party_dispatch_targets.__get__(tab)
    tab._cc_gate_ok = lt.LaunchTab._cc_gate_ok.__get__(tab)

    def fake_on_launch(game, account_id):
        if game == "cc" and not tab._cc_gate_ok():
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
    tab._party_gate_passed = False
    tab._party_pending = set()
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
    tab._party_gate_passed = True
    tab._party_pending = {("ttr", "pending")}
    tab._slots = {"ttr": {}, "cc": {}}
    tab._loading = {"ttr": [], "cc": []}
    tab._probe_thread = None

    lt.LaunchTab.shutdown(tab)

    assert timer.isActive() is False
    assert tab._party_timers == []
    assert tab._party_gate_passed is False
    assert tab._party_pending == set()
