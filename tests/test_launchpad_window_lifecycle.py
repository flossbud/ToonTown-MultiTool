"""The launchpad window's lifecycle and tray, wired: when the window hides,
shows, minimizes or quits on its own, and what the tray icon does. Fake
launcher states and live-toon counts drive it; the tray's reachability is
set per test (the offscreen platform has no tray).

Kept apart from test_launchpad_window.py so each file builds fewer windows:
a LaunchpadWindow leaves about 30 MB behind after it is disposed, which adds
up across one pytest process."""

import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.test_launchpad_window import isolated, window  # noqa: F401 (fixtures)
from utils.widgets.launchpad.header import SHEET_KEYSETS, SHEET_SETTINGS


class _Launches:
    """Drives the window's launch tracker the way the launcher would: a list
    of accounts with LoginState values, plus the party-staged ids."""

    def __init__(self, window, monkeypatch, ids=("a", "b", "c")):
        from services.ttr_login_service import LoginState
        self.S = LoginState
        self.window = window
        self.states = {aid: LoginState.IDLE for aid in ids}
        self.staged = set()
        monkeypatch.setattr(window.launch_tab, "launch_overview", lambda: [
            {"account_id": aid, "game": "ttr", "label": aid, "state": st, "toon": ""}
            for aid, st in self.states.items()])
        monkeypatch.setattr(window.launch_tab, "staged_launches", lambda: set(self.staged))
        window._launch_states = window._read_launch_states()

    def set(self, **states):
        for aid, st in states.items():
            self.states[aid] = getattr(self.S, st.upper())
        self.window.launch_tab.launch_states_changed.emit()


def _toons(window, monkeypatch, n):
    monkeypatch.setattr(window.session, "toons", lambda: [object()] * n)
    window.session.toons_changed.emit()


@pytest.fixture
def lw(window, monkeypatch):
    """The window with a reachable tray, launch states under test control."""
    monkeypatch.setattr(window.tray, "reachable", lambda: True)
    window._sync_tray_reachability()
    return window, _Launches(window, monkeypatch)


def test_hides_on_the_last_landing_not_the_first(lw, monkeypatch, qapp, capsys):
    win, L = lw
    L.set(a="logging_in", b="logging_in")
    _toons(win, monkeypatch, 1)
    L.set(a="running")
    assert win.isVisible()
    _toons(win, monkeypatch, 2)
    L.set(b="running")
    assert not win.isVisible()
    assert "[NextUI] window hidden: all launches landed" in capsys.readouterr().out


def test_a_failed_launch_keeps_the_window_up(lw):
    win, L = lw
    L.set(a="logging_in", b="logging_in")
    L.set(a="failed")
    L.set(b="running")
    assert win.isVisible()


def test_a_cancelled_launch_counts_as_failed(lw):
    win, L = lw
    L.set(a="need_2fa")
    L.set(a="idle")                       # 2FA cancelled
    assert win.isVisible()


def test_party_staged_accounts_are_pending(lw):
    win, L = lw
    L.staged = {"b"}
    L.set(a="logging_in")                 # b waits its turn, still idle itself
    L.set(a="running")
    assert win.isVisible()
    L.staged = set()
    L.set(b="logging_in")
    L.set(b="running")
    assert not win.isVisible()


def test_the_setting_off_keeps_it_up_live(lw):
    from utils.settings_keys import HIDE_WINDOW_WHEN_TOONS_UP
    win, L = lw
    win.settings_manager.set(HIDE_WINDOW_WHEN_TOONS_UP, False)
    L.set(a="logging_in")
    L.set(a="running")
    assert win.isVisible()


def test_shown_again_when_the_last_game_window_closes(lw, monkeypatch, capsys):
    win, L = lw
    _toons(win, monkeypatch, 1)
    L.set(a="logging_in")
    L.set(a="running")
    assert not win.isVisible()
    _toons(win, monkeypatch, 0)
    assert win.isVisible() and win.open_sheet_name() is None
    assert "[NextUI] window shown: last game window closed" in capsys.readouterr().out


def test_a_user_minimize_is_seen(lw, monkeypatch, qapp):
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.showMinimized()
    qapp.processEvents()
    _toons(win, monkeypatch, 0)
    assert win.isVisible() and not win.isMinimized()


def test_no_tray_minimizes_instead_of_hiding(window, monkeypatch, qapp):
    monkeypatch.setattr(window.tray, "reachable", lambda: False)
    L = _Launches(window, monkeypatch)
    L.set(a="logging_in")
    L.set(a="running")
    assert window.isMinimized()           # never hidden with no way back


def test_turning_the_tray_off_while_hidden_minimizes(lw, monkeypatch, qapp):
    from utils.settings_keys import TRAY_ICON
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.close()                           # hides: a game window is up
    assert not win.isVisible()
    monkeypatch.setattr(win.tray, "reachable", lambda: False)
    win.settings_manager.set(TRAY_ICON, False)
    assert win.isMinimized()


def test_close_with_game_windows_hides_and_keeps_running(lw, monkeypatch, isolated):
    win, L = lw
    _toons(win, monkeypatch, 2)
    win.close()
    assert not win.isVisible()
    assert isolated == []                 # did not quit
    assert not win._shutdown_complete


def test_close_with_launches_pending_hides(lw, isolated):
    win, L = lw
    L.set(a="logging_in")
    win.close()
    assert not win.isVisible() and isolated == []


def test_close_with_no_tray_minimizes(window, monkeypatch, isolated):
    monkeypatch.setattr(window.tray, "reachable", lambda: False)
    _toons(window, monkeypatch, 1)
    window.close()
    assert window.isMinimized() and isolated == []


def _record_shutdown_order(window, monkeypatch):
    order = []
    for name, method in (("strips", "shutdown"), ("tray", "shutdown"),
                         ("session", "shutdown")):
        target = getattr(window, name)
        original = getattr(target, method)
        monkeypatch.setattr(target, method,
                            lambda o=original, n=name: (order.append(n), o())[1])
    return order


def test_close_with_nothing_up_quits_strips_first(window, monkeypatch, isolated):
    order = _record_shutdown_order(window, monkeypatch)
    window.close()
    assert isolated == [1]
    assert order[:2] == ["strips", "tray"] and "session" in order


@pytest.mark.parametrize("route", ["quit_app", "home_menu", "tray"])
def test_every_quit_route_quits_even_with_toons_up(window, monkeypatch, isolated, route):
    _toons(window, monkeypatch, 3)
    order = _record_shutdown_order(window, monkeypatch)
    if route == "quit_app":
        window.quit_app()
    elif route == "home_menu":
        window.strips.quit_requested.emit()
    else:
        window.tray.quit_requested.emit()
    assert isolated == [1]
    assert window._shutdown_complete
    assert order[0] == "strips"


def test_quit_from_a_hidden_window(lw, monkeypatch, isolated):
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.close()
    assert not win.isVisible()
    win.tray.quit_requested.emit()
    assert isolated == [1] and win._shutdown_complete


@pytest.mark.parametrize("signal,sheet", [
    ("settings_requested", SHEET_SETTINGS),
    ("launch_accounts_requested", None),
])
def test_tray_rows_show_the_window_on_their_sheet(lw, monkeypatch, qapp, signal, sheet):
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.open_sheet(SHEET_KEYSETS)
    win.close()
    getattr(win.tray, signal).emit()
    assert win.isVisible()
    assert win.open_sheet_name() == sheet


def test_tray_open_brings_it_back_as_it_was_left(lw, monkeypatch):
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.open_sheet(SHEET_KEYSETS)
    win.close()
    win.tray.open_requested.emit()
    assert win.isVisible() and win.open_sheet_name() == SHEET_KEYSETS


def test_tray_stop_start_and_running_state(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.session, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(window.session, "start", lambda: calls.append("start"))
    window.session.running_changed.emit(True)
    assert window.tray.toggle_action.text() == "Stop all toons"
    window.tray.toggle_action.trigger()
    window.session.running_changed.emit(False)
    window.tray.toggle_action.trigger()
    assert calls == ["stop", "start"]


def test_tray_counts_running_accounts(window, monkeypatch):
    from utils.launcher_port import PortAccount
    accts = [PortAccount("a", "ttr", "A", "running", "Flossbud"),
             PortAccount("b", "ttr", "B", "launching", ""),
             PortAccount("c", "cc", "C", "running", "Hiro")]
    monkeypatch.setattr(window.launcher_port, "accounts", lambda: accts)
    window.launch_tab.launch_states_changed.emit()
    assert window.tray.launch_action.text().endswith("2 running ›")


def test_strip_requests_go_through_the_lifecycle(lw, monkeypatch):
    win, L = lw
    _toons(win, monkeypatch, 1)
    win.close()
    assert win.lifecycle.window == "hidden"
    win.strips.open_window_requested.emit("settings")
    assert win.isVisible() and win.lifecycle.window == "visible"
    assert win.open_sheet_name() == SHEET_SETTINGS


def test_the_tray_goes_in_shutdown(window):
    window.shutdown()
    assert not window.tray.is_shown()
