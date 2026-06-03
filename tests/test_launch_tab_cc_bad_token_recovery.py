"""When /login returns bad_token, the status chip shows the 'click Edit'
recovery message."""

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


def test_bad_token_surfaces_click_edit_message(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
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

    def fake_post(url, **kw):
        resp = MagicMock()
        resp.status_code = 401
        body = {"status": False, "success": False,
                "bad_token": True, "message": "Token revoked"}
        resp.json.return_value = body
        # resp.text must be a real string: the service logs
        # _redact_token(resp.text), whose regex rejects a MagicMock.
        import json as _json
        resp.text = _json.dumps(body)
        return resp
    monkeypatch.setattr("requests.post", fake_post)

    # Stub engine-path so the test doesn't require CC installed
    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "/fake/cc/install")
    # The CC launch gate opens a modal install-picker (dlg.exec()) when it
    # discovers installs; under offscreen that blocks forever. No installs ->
    # gate passes straight through.
    monkeypatch.setattr(_lt, "discover_cc_installs", lambda: [])
    import os as _os
    _real_isfile = _os.path.isfile
    monkeypatch.setattr(_os.path, "isfile",
                        lambda p: True if str(p).startswith("/fake/cc/install") else _real_isfile(p))

    from utils.credentials_manager import CredentialsManager
    from tabs.launch_tab import LaunchTab
    from services.ttr_login_service import LoginState
    cm = CredentialsManager()
    cm._probe_complete = True
    cm.add_account(label="Main", username="u@e.com",
                   password="", game="cc")
    acct_id = cm.get_accounts_metadata()[0].id
    cm.set_launcher_token(acct_id, "revoked-tok")

    class _SM:
        def get(self, k, d=""): return d
        def set(self, k, v): pass

    # The terminal failure path pops a modal failure dialog; suppress it so
    # box.exec() can't block the event-loop wait below.
    monkeypatch.setattr(_lt.LaunchTab, "_show_failure_dialog",
                        lambda self, game, account_id, msg: None)

    tab = None
    try:
        tab = LaunchTab(credentials_manager=cm, settings_manager=_SM())
        # The keyring-probe-complete callback rebuilds the slot grid; the slot
        # is the source of truth for FAILED state + the user-facing message.
        def _slot():
            return tab._slots["cc"].get(acct_id)

        tab._on_launch("cc", acct_id)

        assert _wait(
            lambda: _slot() is not None
            and _slot().state == LoginState.FAILED
        )
        # The status message must mention "Edit" + "password" so the user
        # knows the recovery action.
        text = _slot().message
        assert "Edit" in text and "password" in text.lower(), (
            f"Expected 'Edit' + 'password' in status message, got: {text!r}")
    finally:
        if tab is not None:
            # Tear down the live CC worker so no late cross-thread login_failed
            # signal fires _show_failure_dialog during fixture teardown (which
            # would pop a real modal and abort). Nulling slot.worker also makes
            # the worker-identity guard reject any in-flight signal.
            slot = tab._slots["cc"].get(acct_id)
            if slot is not None and slot.worker is not None:
                tab._disconnect_worker_signals(slot.worker)
                try:
                    slot.worker.cancel()
                except Exception:
                    pass
                slot.worker = None
            try:
                tab.shutdown()
            except Exception:
                pass
        if saved is not None:
            keyring_core._keyring_backend = saved
