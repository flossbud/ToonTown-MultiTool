"""Unit tests for LaunchTab._effective_state rehydration precedence and the
loading-queue dedup helper. (The loading machine's end-to-end behavior is
covered by test_launch_tab_loading_state.py.)"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication

from tabs.launch_tab import LaunchTab, AccountSlot
from services.ttr_login_service import LoginState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tab(qapp):
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = []
    sm = MagicMock()
    sm.get.return_value = None
    return LaunchTab(cred_manager=cred, settings_manager=sm)


def test_live_launcher_takes_precedence_running(qapp):
    tab = _tab(qapp)
    # Both a live launcher AND an active loading_timer set: the launcher branch
    # must win (RUNNING), proving its precedence over the timer branch.
    slot = AccountSlot(account_id="a", state=LoginState.IDLE,
                       launcher=SimpleNamespace(is_running=lambda: True),
                       loading_timer=object())
    assert tab._effective_state("ttr", slot) == (LoginState.RUNNING, "Game running", "")


def test_active_loading_timer_yields_loading(qapp):
    tab = _tab(qapp)
    slot = AccountSlot(account_id="a", state=LoginState.IDLE,
                       launcher=SimpleNamespace(is_running=lambda: False),
                       loading_timer=object())
    assert tab._effective_state("ttr", slot) == (LoginState.LOADING, "", "")


def test_stored_running_but_dead_launcher_falls_back_to_idle(qapp):
    tab = _tab(qapp)
    # Stored RUNNING, but the launcher is gone (None) -> must not show "running".
    slot = AccountSlot(account_id="a", state=LoginState.RUNNING, launcher=None)
    assert tab._effective_state("ttr", slot) == (LoginState.IDLE, "", "")


def test_stored_running_but_launcher_not_running_falls_back(qapp):
    tab = _tab(qapp)
    slot = AccountSlot(account_id="a", state=LoginState.RUNNING,
                       launcher=SimpleNamespace(is_running=lambda: False))
    assert tab._effective_state("ttr", slot) == (LoginState.IDLE, "", "")


def test_stored_state_passthrough_when_no_launcher_or_timer(qapp):
    tab = _tab(qapp)
    slot = AccountSlot(account_id="a", state=LoginState.FAILED,
                       message="bad creds", raw_error="HTTP 401")
    assert tab._effective_state("ttr", slot) == (LoginState.FAILED, "bad creds", "HTTP 401")


def test_loading_add_dedups(qapp):
    tab = _tab(qapp)
    tab._loading_add("ttr", "a")
    tab._loading_add("ttr", "a")
    tab._loading_add("ttr", "b")
    assert tab._loading["ttr"] == ["a", "b"]  # no duplicate "a"


def test_loading_remove_is_safe_when_absent(qapp):
    tab = _tab(qapp)
    tab._loading_add("ttr", "a")
    tab._loading_remove("ttr", "missing")  # no error
    tab._loading_remove("ttr", "a")
    assert tab._loading["ttr"] == []


def test_loading_remove_preserves_remaining_order(qapp):
    tab = _tab(qapp)
    for aid in ("a", "b", "c"):
        tab._loading_add("ttr", aid)
    tab._loading_remove("ttr", "a")          # remove from the front (FIFO head)
    assert tab._loading["ttr"] == ["b", "c"]  # order of the rest preserved
    tab._loading_remove("ttr", "c")          # remove from the tail
    assert tab._loading["ttr"] == ["b"]
