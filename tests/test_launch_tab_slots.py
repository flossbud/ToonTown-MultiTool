import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from tabs.launch_tab import LaunchTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid, game, label="L", username="u"):
    return SimpleNamespace(id=aid, game=game, label=label, username=username,
                           password="pw", launcher_token="")


def _tab(qapp, accounts):
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    sm = MagicMock()
    sm.get.return_value = None
    return LaunchTab(cred_manager=cred, settings_manager=sm)


def test_reconcile_creates_slots_per_account(qapp):
    tab = _tab(qapp, [_meta("a", "ttr"), _meta("b", "ttr"), _meta("c", "cc")])
    tab._reconcile_slots()
    assert set(tab._slots["ttr"]) == {"a", "b"}
    assert set(tab._slots["cc"]) == {"c"}


def test_reconcile_preserves_existing_slot_objects(qapp):
    tab = _tab(qapp, [_meta("a", "ttr")])
    tab._reconcile_slots()
    slot_a = tab._slots["ttr"]["a"]
    slot_a.state = "running"
    tab._reconcile_slots()
    assert tab._slots["ttr"]["a"] is slot_a
    assert tab._slots["ttr"]["a"].state == "running"


def test_reconcile_drops_removed_account_slots(qapp):
    tab = _tab(qapp, [_meta("a", "ttr"), _meta("b", "ttr")])
    tab._reconcile_slots()
    tab.cred_manager.get_accounts_metadata.return_value = [_meta("a", "ttr")]
    tab._reconcile_slots()
    assert set(tab._slots["ttr"]) == {"a"}


def test_ordered_accounts_filters_by_game_preserving_flat_order(qapp):
    tab = _tab(qapp, [_meta("a", "ttr"), _meta("c", "cc"), _meta("b", "ttr")])
    ttr = [a.id for a in tab._ordered_accounts("ttr")]
    assert ttr == ["a", "b"]
