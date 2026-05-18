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
        lambda self, game, idx, msg: calls.append((game, idx, msg)),
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
    long_msg = (
        "We've noticed that you're logging in from a new device/IP, "
        "please check your email and activate this session before "
        "continuing."
    )

    tab._on_login_failed("cc", 0, long_msg)

    assert recorded_calls == [("cc", 0, long_msg)]


def test_on_launcher_failed_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """launcher_failed signal -> dialog. Covers _on_launcher_failed."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Main", username="u@e.com", password="p",
                   game="cc")

    tab._on_launcher_failed("cc", 0, "Wine exited 1")

    assert recorded_calls == [("cc", 0, "Wine exited 1")]


def test_missing_username_sync_validation_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """Clicking Launch on an account with no username -> sync FAILED ->
    dialog. Covers _on_launch missing-username branch."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Empty", username="", password="",
                   game="ttr")
    # _build_ui must run after add_account so that self._cards["ttr"] is
    # populated with the new row; otherwise _on_launch bails on the
    # section_index range guard before reaching the validation branches.
    tab._build_ui()

    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "/fake/ttr/install")
    import os as _os
    _real_isfile = _os.path.isfile
    monkeypatch.setattr(_os.path, "isfile",
                        lambda p: True if p.startswith("/fake/") else _real_isfile(p))

    tab._on_launch("ttr", 0)

    assert len(recorded_calls) == 1
    game, idx, msg = recorded_calls[0]
    assert (game, idx) == ("ttr", 0)
    assert "username" in msg.lower()


def test_engine_path_missing_pops_dialog(
    qapp, monkeypatch, tmp_path, recorded_calls
):
    """Clicking Launch when engine dir is unset -> sync FAILED -> dialog.
    Covers _on_launch engine-path-missing branch."""
    tab, cm = _make_tab(monkeypatch, tmp_path)
    cm.add_account(label="Main", username="u@e.com", password="p",
                   game="ttr")
    # _build_ui must run after add_account so that self._cards["ttr"] is
    # populated with the new row; otherwise _on_launch bails on the
    # section_index range guard before reaching the engine-path check.
    tab._build_ui()

    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "")

    tab._on_launch("ttr", 0)

    assert len(recorded_calls) == 1
    game, idx, msg = recorded_calls[0]
    assert (game, idx) == ("ttr", 0)
    assert "game path" in msg.lower() or "engine" in msg.lower()
