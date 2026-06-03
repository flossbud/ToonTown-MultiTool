import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from tabs.launch_tab import LaunchTab
from services.ttr_login_service import LoginState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid, game):
    return SimpleNamespace(id=aid, game=game, label=aid, username=aid, password="pw", launcher_token="")


def _tab(qapp, accounts):
    cred = MagicMock(); cred.keyring_available = True; cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account.side_effect = lambda gi: accounts[gi]
    sm = MagicMock(); sm.get.return_value = None
    return LaunchTab(cred_manager=cred, settings_manager=sm)


def test_update_status_writes_slot_and_visible_tile(qapp):
    tab = _tab(qapp, [_meta("a", "ttr"), _meta("b", "ttr")])
    tab._build_ui()
    tab._update_status("ttr", "b", LoginState.FAILED, "nope")
    assert tab._slots["ttr"]["b"].state == LoginState.FAILED
    assert tab._slots["ttr"]["b"].message == "nope"
    assert tab._visible_tiles["ttr"]["b"] is not None


def test_update_status_offpage_updates_slot_only(qapp):
    tab = _tab(qapp, [_meta(f"t{i}", "ttr") for i in range(6)])
    tab._build_ui()
    tab._update_status("ttr", "t5", LoginState.FAILED, "x")
    assert tab._slots["ttr"]["t5"].state == LoginState.FAILED
    assert "t5" not in tab._visible_tiles["ttr"]
    tab._on_page_changed("ttr", 1)
    assert tab.ttr_section.tiles[1].badge.text() == "6"


def test_stale_worker_state_signal_is_ignored(qapp):
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._build_ui()
    slot = tab._slots["ttr"]["a"]
    old_worker = SimpleNamespace(); new_worker = SimpleNamespace()
    slot.worker = new_worker; slot.state = LoginState.LOGGING_IN
    tab._on_worker_state("ttr", "a", old_worker, LoginState.FAILED, "stale")
    assert slot.state == LoginState.LOGGING_IN
    tab._on_worker_state("ttr", "a", new_worker, LoginState.RUNNING, "ok")
    assert slot.state == LoginState.RUNNING


def test_tile_launch_signal_routes_to_on_launch(qapp, monkeypatch):
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._build_ui()
    seen = []
    monkeypatch.setattr(tab, "_on_launch", lambda g, a: seen.append((g, a)))
    tab.ttr_section.tile_launch.emit("a")
    assert seen == [("ttr", "a")]


def test_stale_launcher_game_exited_is_ignored(qapp):
    # A superseded launcher firing game_exited must not reset the live slot.
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._build_ui()
    slot = tab._slots["ttr"]["a"]
    live = SimpleNamespace(is_running=lambda: True)
    stale = SimpleNamespace(is_running=lambda: False)
    slot.launcher = live
    slot.state = LoginState.RUNNING
    tab._on_game_exited("ttr", "a", stale, 1, "boom")  # stale launcher
    assert slot.state == LoginState.RUNNING  # unchanged
    tab._on_game_exited("ttr", "a", live, 0, "")  # current launcher -> IDLE
    assert slot.state == LoginState.IDLE


def test_stale_launcher_failed_is_ignored(qapp):
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._build_ui()
    slot = tab._slots["ttr"]["a"]
    live = SimpleNamespace(is_running=lambda: True)
    stale = SimpleNamespace(is_running=lambda: False)
    slot.launcher = live
    slot.state = LoginState.RUNNING
    tab._on_launcher_failed("ttr", "a", stale, "stale failure")
    assert slot.state == LoginState.RUNNING  # unchanged by stale launcher


def test_cancel_detaches_worker_so_late_success_is_ignored(qapp):
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._build_ui()
    slot = tab._slots["ttr"]["a"]
    w = SimpleNamespace(cancel=lambda: None)
    slot.worker = w
    slot.state = LoginState.LOGGING_IN
    tab._on_tile_cancel("ttr", "a")
    assert slot.worker is None  # detached on cancel
    # A late signal from the cancelled worker no longer passes the identity guard.
    tab._on_worker_state("ttr", "a", w, LoginState.RUNNING, "late")
    assert slot.state == LoginState.IDLE  # not flipped by the stale worker


def test_stale_register_worker_token_is_ignored(qapp):
    # A token from a superseded register worker must not persist/clear password.
    tab = _tab(qapp, [_meta("a", "cc")])
    tab._build_ui()
    slot = tab._slots["cc"]["a"]
    new_worker = SimpleNamespace()
    slot.worker = new_worker
    called = []
    tab._persist_launcher_token = lambda aid, tok: called.append((aid, tok))
    old_worker = SimpleNamespace()
    tab._on_token_obtained("cc", "a", old_worker, "tok")   # stale -> ignored
    assert called == []
    tab._on_token_obtained("cc", "a", new_worker, "tok2")  # current -> persists
    assert called == [("a", "tok2")]
