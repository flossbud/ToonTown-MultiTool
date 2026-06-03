"""Every terminal login/launch failure pops a single dialog with the full message.

Strategy: monkeypatch LaunchTab._show_failure_dialog with a recorder, then
trigger each representative failure path. Spec lists seven dispatch sites;
we exercise one site per logical category (sync validation, worker signal,
post-login engine resolution).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def recorded_calls(monkeypatch):
    """Replace _show_failure_dialog on the class so every LaunchTab uses
    the recorder. Returns the call list."""
    calls = []
    from tabs.launch_tab import LaunchTab
    monkeypatch.setattr(
        LaunchTab, "_show_failure_dialog",
        lambda self, game, account_id, msg: calls.append((game, account_id, msg)),
    )
    return calls


def _make_tab(monkeypatch, tmp_path):
    """Build a LaunchTab in the same way the existing CC token-flow test
    does. Returns (tab, cred_manager)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import keyring
    from keyring.backend import KeyringBackend

    class _Mem(KeyringBackend):
        priority = 999
        def __init__(self): self.store = {}
        def get_password(self, s, u): return self.store.get((s, u))
        def set_password(self, s, u, p): self.store[(s, u)] = p
        def delete_password(self, s, u): self.store.pop((s, u), None)

    keyring.set_keyring(_Mem())

    from utils.credentials_manager import CredentialsManager
    from tabs.launch_tab import LaunchTab
    cm = CredentialsManager()
    cm._probe_complete = True

    class _SM:
        def get(self, k, d=""): return d
        def set(self, k, v): pass

    tab = LaunchTab(credentials_manager=cm, settings_manager=_SM())
    return tab, cm


def test_on_login_failed_pops_dialog_with_full_message(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """Worker-emitted login_failed -> exactly one dialog with the full
    server message. Covers dispatch site _on_login_failed."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Main", username="u@e.com", password="p",
                   game="cc")
    tab._build_ui()  # populate the cc slot for this account
    aid = tab._ordered_accounts("cc")[0].id
    # The handler ignores stale signals: the emitting worker must be the
    # slot's current worker. Install a sentinel worker on the slot.
    worker = object()
    tab._slots["cc"][aid].worker = worker
    long_msg = (
        "We've noticed that you're logging in from a new device/IP, "
        "please check your email and activate this session before "
        "continuing."
    )

    tab._on_login_failed("cc", aid, worker, long_msg)

    assert recorded_calls == [("cc", aid, long_msg)]


def test_on_launcher_failed_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """launcher_failed signal -> dialog. Covers _on_launcher_failed."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Main", username="u@e.com", password="p",
                   game="cc")
    tab._build_ui()
    aid = tab._ordered_accounts("cc")[0].id

    class _L:
        def is_running(self): return False
    launcher = _L()
    tab._slots["cc"][aid].launcher = launcher

    tab._on_launcher_failed("cc", aid, launcher, "Wine exited 1")

    assert recorded_calls == [("cc", aid, "Wine exited 1")]


def test_missing_username_sync_validation_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """Clicking Launch on an account with no username -> sync FAILED ->
    dialog. Covers _on_launch missing-username branch."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Empty", username="", password="",
                   game="ttr")
    # _build_ui must run after add_account so that the ttr slot is
    # reconciled; otherwise _on_launch bails on the missing-slot guard
    # before reaching the validation branches.
    tab._build_ui()
    aid = tab._ordered_accounts("ttr")[0].id

    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "/fake/ttr/install")
    import os as _os
    _real_isfile = _os.path.isfile
    monkeypatch.setattr(_os.path, "isfile",
                        lambda p: True if p.startswith("/fake/") else _real_isfile(p))

    tab._on_launch("ttr", aid)

    assert len(recorded_calls) == 1
    game, account_id, msg = recorded_calls[0]
    assert (game, account_id) == ("ttr", aid)
    assert "username" in msg.lower()


def test_engine_path_missing_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """Clicking Launch when engine dir is unset -> sync FAILED -> dialog.
    Covers _on_launch engine-path-missing branch."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Main", username="u@e.com", password="p",
                   game="ttr")
    # _build_ui must run after add_account so that the ttr slot is
    # reconciled; otherwise _on_launch bails on the missing-slot guard
    # before reaching the engine-path check.
    tab._build_ui()
    aid = tab._ordered_accounts("ttr")[0].id

    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "")

    tab._on_launch("ttr", aid)

    assert len(recorded_calls) == 1
    game, account_id, msg = recorded_calls[0]
    assert (game, account_id) == ("ttr", aid)
    assert "game path" in msg.lower() or "engine" in msg.lower()
