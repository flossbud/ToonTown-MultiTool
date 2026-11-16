"""LauncherPort: the launcher as the float strips' compact launcher sees it."""

import pytest
from PySide6.QtCore import QObject, Signal

from services.ttr_login_service import LoginState
from utils.launcher_port import (
    STATE_IDLE, STATE_LAUNCHING, STATE_RUNNING, LauncherPort, PortAccount, port_state,
)


class FakeLaunchTab(QObject):
    accounts_changed = Signal()

    def __init__(self, items):
        super().__init__()
        self.items = [dict(i) for i in items]
        self.launched = []

    def launch_overview(self):
        return [dict(i) for i in self.items]

    def game_of_account(self, account_id):
        return next((i["game"] for i in self.items if i["account_id"] == account_id), None)

    def launch_account(self, game, account_id):
        self.launched.append((game, account_id))


def item(account_id, game="ttr", label="acct", state=LoginState.IDLE, toon=""):
    return {"account_id": account_id, "game": game, "label": label,
            "state": state, "toon": toon}


@pytest.mark.parametrize("login_state, expected", [
    (LoginState.IDLE, STATE_IDLE), (LoginState.FAILED, STATE_IDLE),
    (LoginState.LOGGING_IN, STATE_LAUNCHING), (LoginState.NEED_2FA, STATE_LAUNCHING),
    (LoginState.QUEUED, STATE_LAUNCHING), (LoginState.LAUNCHING, STATE_LAUNCHING),
    (LoginState.LOADING, STATE_LAUNCHING), (LoginState.RUNNING, STATE_RUNNING),
    ("something-new", STATE_IDLE),
])
def test_port_state(login_state, expected):
    assert port_state(login_state) == expected


def test_accounts_in_launcher_order_with_the_three_states(qapp):
    tab = FakeLaunchTab([
        item("a", label="Main", state=LoginState.RUNNING, toon="Flossbud"),
        item("b", label="alt", state=LoginState.LOADING, toon="Hector"),
        item("c", game="cc", label="clash", toon="Moe"),
    ])
    port = LauncherPort(tab)
    assert port.accounts() == [
        PortAccount("a", "ttr", "Main", "running", "Flossbud"),
        PortAccount("b", "ttr", "alt", "launching", ""),      # not in a game yet
        PortAccount("c", "cc", "clash", "idle", ""),
    ]


def test_launch_goes_through_the_launchers_own_entry(qapp):
    tab = FakeLaunchTab([item("a"), item("c", game="cc")])
    port = LauncherPort(tab)
    assert port.launch("c") is True
    assert port.launch("unknown") is False
    assert tab.launched == [("cc", "c")]


def test_changed_fires_only_when_what_it_reports_changed(qapp):
    tab = FakeLaunchTab([item("a"), item("b")])
    port = LauncherPort(tab)
    seen = []
    port.changed.connect(lambda: seen.append(1))
    tab.accounts_changed.emit()                     # a re-render, nothing new
    assert seen == []
    tab.items[0]["state"] = LoginState.LOGGING_IN
    tab.accounts_changed.emit()
    assert seen == [1]
    tab.items[0]["state"] = LoginState.QUEUED       # still "launching"
    tab.accounts_changed.emit()
    assert seen == [1]
    tab.items.append(item("c"))
    tab.accounts_changed.emit()
    assert seen == [1, 1]
    tab.items[1]["toon"] = "Idle Toon"              # not running: toon not shown
    tab.accounts_changed.emit()
    assert seen == [1, 1]
