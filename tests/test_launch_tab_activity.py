"""End-to-end: running state survives page flips and pager activity rings
reflect off-page running/loading games (validates the T6 render flow + the
slot model wired in T7)."""
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


def _meta(aid):
    return SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                           password="pw", launcher_token="")


def _tab(qapp, n):
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = [_meta(f"t{i}") for i in range(n)]
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()
    return tab


def test_running_game_survives_page_flip(qapp):
    tab = _tab(qapp, 6)  # 2 pages (t0-t3, t4-t5)
    tab._slots["ttr"]["t0"].launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["t0"].state = LoginState.RUNNING
    tab._on_page_changed("ttr", 1)   # flip away from t0
    tab._on_page_changed("ttr", 0)   # flip back
    # The rebuilt tile for t0 reflects RUNNING, derived live from the launcher.
    st, _, _ = tab._effective_state("ttr", tab._slots["ttr"]["t0"])
    assert st == LoginState.RUNNING
    tile = tab._visible_tiles["ttr"]["t0"]
    assert tile.badge.text() == "1"


def test_activity_ring_marks_page_with_running_game(qapp):
    tab = _tab(qapp, 6)  # page 1 holds t4, t5
    tab._slots["ttr"]["t5"].launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["t5"].state = LoginState.RUNNING
    flags = tab._page_activity("ttr", tab._ordered_accounts("ttr"), 2)
    assert flags == [False, True]


def test_activity_ring_marks_loading_account(qapp):
    tab = _tab(qapp, 2)  # single page + reserved landing page (2 dots)
    tab._slots["ttr"]["t1"].loading_timer = object()  # mid-load
    tab._slots["ttr"]["t1"].state = LoginState.LOADING
    flags = tab._page_activity("ttr", tab._ordered_accounts("ttr"), 2)
    assert flags[0] is True   # page 0 holds t0,t1 -> active


def test_idle_pages_have_no_activity(qapp):
    tab = _tab(qapp, 6)
    flags = tab._page_activity("ttr", tab._ordered_accounts("ttr"), 2)
    assert flags == [False, False]
