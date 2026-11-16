"""The compact launcher's adapter observes launch state without roster renders."""
from PySide6.QtCore import Signal
from tests.test_launcher_port import FakeLaunchTab, item
from services.ttr_login_service import LoginState
from utils.launcher_port import LauncherPort


class StatefulLaunchTab(FakeLaunchTab):
    launch_states_changed = Signal()


def test_state_changes_refresh_port_without_accounts_changed(qapp):
    tab = StatefulLaunchTab([item('main')])
    port = LauncherPort(tab)
    seen = []
    port.changed.connect(lambda: seen.append((port.accounts()[0].state, port.accounts()[0].toon)))
    tab.items[0]['state'] = LoginState.LOGGING_IN
    tab.launch_states_changed.emit()
    assert seen == [('launching', '')]
    tab.items[0]['state'] = LoginState.QUEUED
    tab.launch_states_changed.emit()
    assert seen == [('launching', '')]  # no duplicate compact-state notification
    tab.items[0].update(state=LoginState.RUNNING, toon='Fresh Toon')
    tab.launch_states_changed.emit()
    assert seen[-1] == ('running', 'Fresh Toon')
    tab.items[0]['state'] = LoginState.IDLE
    tab.launch_states_changed.emit()
    assert seen == [('launching', ''), ('running', 'Fresh Toon'), ('idle', '')]
