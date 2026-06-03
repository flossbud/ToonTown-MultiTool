"""Regression: deleting a mid-list account must not misattribute a RUNNING
game to the wrong account.

Before the account_id slot model, runtime state (_workers/_launchers) was keyed
by grid position while cred_manager re-indexed accounts on delete, so deleting
an earlier account shifted a running game's launcher onto the wrong tile. Keying
runtime state by stable account_id removes that class of bug. This test pins it.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication

import tabs.launch_tab as launch_tab
from tabs.launch_tab import LaunchTab
from services.ttr_login_service import LoginState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid):
    return SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                           password="pw", launcher_token="")


def test_deleting_an_account_does_not_misattribute_a_running_game(qapp, monkeypatch):
    accounts = [_meta("A"), _meta("B"), _meta("C"), _meta("D")]
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account_metadata.side_effect = lambda gi: accounts[gi]

    def _delete(gi):
        accounts.pop(gi)          # mirror CredentialsManager: re-indexes the rest
        return ("X", "")
    cred.delete_account.side_effect = _delete

    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()

    # C is running.
    tab._slots["ttr"]["C"].launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["C"].state = LoginState.RUNNING

    # Auto-accept the delete confirm dialog (the symbol launch_tab actually uses).
    class _OK:
        class DialogCode:
            Accepted = 1
        def __init__(self, *a, **k):
            pass
        def exec(self):
            return 1
    monkeypatch.setattr(launch_tab, "ConfirmDialog", _OK)

    # Delete B (the account at flat index 1, BEFORE the running C).
    tab._on_delete("ttr", "B")

    # C's RUNNING state stays attached to C, not shifted onto D.
    assert "C" in tab._slots["ttr"]
    st_c, _, _ = tab._effective_state("ttr", tab._slots["ttr"]["C"])
    assert st_c == LoginState.RUNNING, "running game must stay on C after deleting B"

    # D never launched -> still idle (it did NOT inherit C's running state).
    assert "D" in tab._slots["ttr"]
    st_d, _, _ = tab._effective_state("ttr", tab._slots["ttr"]["D"])
    assert st_d == LoginState.IDLE

    # B is gone.
    assert "B" not in tab._slots["ttr"]
