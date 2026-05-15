"""Clicking Launch on a CC account without a stored token triggers
register_and_login, persists the launcher token, and clears the password."""

import time
from unittest.mock import MagicMock
import pytest


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(predicate, timeout=2.0):
    """Busy-wait helper. Calls QCoreApplication.processEvents() each tick
    so cross-thread queued Qt signals (worker daemon thread -> main thread
    slots) actually deliver during the wait."""
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_cc_account_without_token_runs_register_flow(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Stub keyring (same robust pattern Tasks 1-2 established).
    import keyring
    from keyring.backend import KeyringBackend
    import keyring.core as keyring_core
    class _Mem(KeyringBackend):
        priority = 999
        def __init__(self): self.store = {}
        def get_password(self, s, u): return self.store.get((s, u))
        def set_password(self, s, u, p): self.store[(s, u)] = p
        def delete_password(self, s, u): self.store.pop((s, u), None)
    backend = _Mem()
    saved = getattr(keyring_core, "_keyring_backend", None)
    keyring.set_keyring(backend)

    # Stub the network: register OK, login OK, metadata stubbed.
    from services.cc_login_service import CCLoginWorker
    monkeypatch.setattr(CCLoginWorker, "_fetch_gameserver",
                        lambda self, t: "gs:1")
    def fake_post(url, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = (
            {"status": True, "token": "launcher-tok"}
            if "register" in url else
            {"status": True, "success": True, "token": "game-tok"}
        )
        return resp
    monkeypatch.setattr("requests.post", fake_post)

    from utils.credentials_manager import CredentialsManager
    from tabs.launch_tab import LaunchTab
    cm = CredentialsManager()
    cm._probe_complete = True  # bypass probe gate for keyring writes
    cm.add_account(label="Main", username="u@e.com",
                   password="pw", game="cc")
    class _SM:
        def get(self, k, d=""): return d
        def set(self, k, v): pass
    try:
        tab = LaunchTab(credentials_manager=cm, settings_manager=_SM())
        tab._on_launch("cc", 0)
        # Daemon thread runs the chain; wait for token persistence.
        assert _wait(lambda: cm.get_launcher_token(cm.get_accounts_metadata()[0].id) == "launcher-tok")
        # Password should be cleared (token-only model).
        acct = cm.get_accounts_metadata()[0]
        assert acct.password == ""
    finally:
        if saved is not None:
            keyring_core._keyring_backend = saved
