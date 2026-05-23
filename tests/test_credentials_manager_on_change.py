"""Covers CredentialsManager.on_change callback registration + emission."""
from __future__ import annotations

import pytest

from utils.credentials_manager import CredentialsManager


@pytest.fixture
def cred_manager(tmp_path, monkeypatch):
    """Build a CredentialsManager pointed at a temp config dir so tests
    don't touch the user's real ~/.config/toontown_multitool."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # The manager probes the keyring at construction; force fallback so
    # tests don't depend on the host keyring backend.
    monkeypatch.setattr(
        "utils.credentials_manager.CredentialsManager._try_keyring_call",
        lambda self, *a, **kw: None,
    )
    mgr = CredentialsManager()
    mgr._use_keyring = False
    return mgr


def test_on_change_callback_registers(cred_manager):
    fired = []
    cred_manager.on_change(lambda: fired.append("hit"))
    # Trivially, the registration itself doesn't fire.
    assert fired == []


def test_add_account_fires_on_change(cred_manager):
    fired = []
    cred_manager.on_change(lambda: fired.append("hit"))
    cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    assert fired == ["hit"]


def test_delete_account_fires_on_change(cred_manager):
    cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    fired = []
    cred_manager.on_change(lambda: fired.append("hit"))
    cred_manager.delete_account(0)
    assert fired == ["hit"]


def test_clear_all_fires_on_change(cred_manager):
    cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    cred_manager.add_account(label="B", username="b", password="p", game="cc")
    fired = []
    cred_manager.on_change(lambda: fired.append("hit"))
    cred_manager.clear_all()
    assert fired == ["hit"]


def test_multiple_callbacks_all_fire(cred_manager):
    a, b = [], []
    cred_manager.on_change(lambda: a.append(1))
    cred_manager.on_change(lambda: b.append(1))
    cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    assert a == [1]
    assert b == [1]


def test_callback_exception_does_not_propagate(cred_manager):
    """A bad callback must not prevent later callbacks from running and
    must not raise out of the mutator."""
    fired = []

    def bad():
        raise RuntimeError("simulated callback failure")

    cred_manager.on_change(bad)
    cred_manager.on_change(lambda: fired.append("after-bad"))
    # Must not raise.
    result = cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    assert result is True
    assert fired == ["after-bad"]


def test_update_account_does_not_fire(cred_manager):
    """update_account doesn't change the game tag, so game-active state
    can't change. Per the spec we emit only on add/delete/clear_all."""
    cred_manager.add_account(label="A", username="a", password="p", game="ttr")
    fired = []
    cred_manager.on_change(lambda: fired.append("hit"))
    cred_manager.update_account(0, label="A-renamed")
    assert fired == []
