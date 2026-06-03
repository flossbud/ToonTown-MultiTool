import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import types
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
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    sm = MagicMock()
    sm.get.return_value = None
    return LaunchTab(cred_manager=cred, settings_manager=sm)


def _stub_editor_factory(invoke_save=True, save_args=("L", "u", "pw")):
    """Return a factory that produces a stub AccountEditor.

    When invoke_save=True, calling .exec() immediately fires the
    account_saved callback with save_args. When False, exec() is a no-op
    (simulating user cancel).
    """
    def factory(*a, **k):
        ed = types.SimpleNamespace()
        cb_holder = []

        class _Sig:
            def connect(self, f):
                cb_holder.append(f)

        ed.account_saved = _Sig()

        def exec_fn():
            if invoke_save and cb_holder:
                cb_holder[0](*save_args)

        ed.exec = exec_fn
        return ed

    return factory


def test_navigate_to_account_sets_page_by_filtered_position(qapp):
    accounts = [_meta(f"t{i}", "ttr") for i in range(4)]
    tab = _tab(qapp, accounts)
    tab._build_ui()
    # Add a 5th account that would land on page 1 (filtered index 4, PAGE_SIZE=4).
    accounts.append(_meta("t4", "ttr"))
    tab._navigate_to_account("ttr", "t4")
    assert tab._page["ttr"] == 1  # filtered index 4 -> page 1


def test_navigate_uses_filtered_position_in_interleaved_flat_order(qapp):
    accounts = [_meta(f"t{i}", "ttr") for i in range(4)] + [_meta("c0", "cc")]
    tab = _tab(qapp, accounts)
    tab._build_ui()
    # Insert a new TTR account at flat index 2; TTR-filtered order: t0,t1,t4,t2,t3
    accounts.insert(2, _meta("t4", "ttr"))
    tab._navigate_to_account("ttr", "t4")
    assert tab._page["ttr"] == 0  # TTR filtered index 2 -> page 0


def test_add_account_navigates_to_new_accounts_page(qapp):
    accounts = [_meta(f"t{i}", "ttr") for i in range(4)]
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts

    def _add(label, username, password, game):
        new = _meta("t4", game)
        accounts.append(new)
        return True  # add_account returns True on success

    cred.add_account.side_effect = _add
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()

    import tabs.launch_tab as lt
    lt.AccountEditor = _stub_editor_factory(invoke_save=True, save_args=("L", "u", "pw"))
    tab._on_add_account("ttr")
    assert tab._page["ttr"] == 1  # navigated to 5th account's page (index 4 -> page 1)


def test_add_account_is_noop_at_ceiling(qapp):
    accounts = [_meta(f"t{i}", "ttr") for i in range(16)]
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()

    import tabs.launch_tab as lt
    editor_called = []

    def _no_call_factory(*a, **k):
        editor_called.append(1)
        return _stub_editor_factory()(*a, **k)

    lt.AccountEditor = _no_call_factory
    tab._on_add_account("ttr")  # at ceiling -> must NOT open editor or call add_account
    cred.add_account.assert_not_called()
    assert editor_called == [], "AccountEditor must not be constructed at the 16-account ceiling"


def test_edit_is_game_scoped(qapp):
    accounts = [_meta("a", "ttr")]
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account.return_value = accounts[0]
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()

    import tabs.launch_tab as lt
    seen = {}

    def _capture_factory(*a, **k):
        seen["game"] = k.get("game")
        return _stub_editor_factory(invoke_save=False)(*a, **k)

    lt.AccountEditor = _capture_factory
    tab._on_tile_edit("ttr", "a")
    assert seen.get("game") == "ttr"  # editor constructed with the account's game


def test_delete_active_account_tears_down(qapp):
    accounts = [_meta("a", "ttr")]
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account_metadata.return_value = accounts[0]

    def _delete(idx):
        # Mutate the accounts list so _reconcile_slots sees an empty roster
        # after deletion, matching what the real CredentialsManager does.
        accounts.clear()
        return ("a", "")

    cred.delete_account.side_effect = _delete
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()

    killed = []
    cancelled = []
    slot = tab._slots["ttr"]["a"]
    slot.worker = SimpleNamespace(cancel=lambda: cancelled.append(1))
    slot.launcher = SimpleNamespace(is_running=lambda: True, kill=lambda: killed.append(1))

    import tabs.launch_tab as lt

    class _AcceptDialog:
        DialogCode = SimpleNamespace(Accepted=1)

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 1

    lt.ConfirmDialog = _AcceptDialog
    tab._on_delete("ttr", "a")
    assert cancelled == [1], "worker.cancel() must be called on delete"
    assert killed == [1], "launcher.kill() must be called on delete"
    assert "a" not in tab._slots["ttr"], "slot must be removed after delete"
