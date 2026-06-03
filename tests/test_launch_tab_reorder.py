import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QDialog
from tabs.launch_tab import LaunchTab
from services.ttr_login_service import LoginState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid, game="ttr"):
    return SimpleNamespace(id=aid, game=game, label=aid, username=aid, password="pw", launcher_token="")


def _tab(qapp, accounts):
    cred = MagicMock(); cred.keyring_available = True; cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    cred.reorder_game.return_value = True
    sm = MagicMock(); sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()
    return tab


def test_reorder_chip_hidden_below_two_accounts(qapp):
    tab = _tab(qapp, [_meta("a")])
    assert not tab.ttr_section.pager.reorder_btn.isVisibleTo(tab.ttr_section)


def test_reorder_chip_shown_at_two_plus(qapp):
    tab = _tab(qapp, [_meta("a"), _meta("b")])
    # isVisibleTo checks show/hide state relative to ancestor without needing
    # the top-level window to be shown (QWidget.isVisible() returns False for
    # unshown top-levels in offscreen tests).
    assert tab.ttr_section.pager.reorder_btn.isVisibleTo(tab.ttr_section)


def test_on_reorder_applies_dialog_order(qapp, monkeypatch):
    accounts = [_meta("a"), _meta("b"), _meta("c")]
    tab = _tab(qapp, accounts)
    import tabs.launch_tab as lt

    class _FakeDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def ordered_ids(self): return ["c", "a", "b"]
    monkeypatch.setattr(lt, "AccountReorderDialog", _FakeDialog)

    tab._on_reorder("ttr")
    tab.cred_manager.reorder_game.assert_called_once_with("ttr", ["c", "a", "b"])


def test_on_reorder_cancel_does_not_apply(qapp, monkeypatch):
    tab = _tab(qapp, [_meta("a"), _meta("b")])
    import tabs.launch_tab as lt

    class _CancelDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Rejected
        def ordered_ids(self): return ["b", "a"]
    monkeypatch.setattr(lt, "AccountReorderDialog", _CancelDialog)

    tab._on_reorder("ttr")
    tab.cred_manager.reorder_game.assert_not_called()


def test_running_account_survives_reorder(qapp, monkeypatch):
    accounts = [_meta("a"), _meta("b")]
    tab = _tab(qapp, accounts)
    tab._slots["ttr"]["b"].launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["b"].state = LoginState.RUNNING
    import tabs.launch_tab as lt

    class _FakeDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def ordered_ids(self): return ["b", "a"]
    monkeypatch.setattr(lt, "AccountReorderDialog", _FakeDialog)
    def _reorder(game, ids):
        accounts.sort(key=lambda m: ids.index(m.id)); return True
    tab.cred_manager.reorder_game.side_effect = _reorder

    tab._on_reorder("ttr")
    st, _, _ = tab._effective_state("ttr", tab._slots["ttr"]["b"])
    assert st == LoginState.RUNNING
    assert [a.id for a in tab._ordered_accounts("ttr")] == ["b", "a"]
