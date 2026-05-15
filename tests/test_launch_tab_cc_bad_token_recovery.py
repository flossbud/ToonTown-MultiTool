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
        resp.json.return_value = {
            "status": False, "success": False,
            "bad_token": True, "message": "Token revoked"}
        return resp
    monkeypatch.setattr("requests.post", fake_post)

    # Stub engine-path so the test doesn't require CC installed
    import tabs.launch_tab as _lt
    monkeypatch.setattr(_lt.LaunchTab, "_get_engine_dir",
                        lambda self, game: "/fake/cc/install")
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

    try:
        tab = LaunchTab(credentials_manager=cm, settings_manager=_SM())
        tab._on_launch("cc", 0)
        # Wait for the FAILED state to land. Re-acquire the card on each
        # tick because the keyring-probe-complete callback rebuilds
        # _cards via _build_ui(), invalidating any earlier reference.
        def _card():
            cards = tab._cards["cc"]
            return cards[0] if cards else None

        assert _wait(
            lambda: _card() is not None
            and _card().get("state") == LoginState.FAILED
        )
        card = _card()
        # The status chip / banner must mention "Edit" so the user knows what to do.
        # _update_status sets the chip text via card["status_chip"].set_status(state, message).
        # Read whichever attribute the chip exposes.
        chip = card["status_chip"]
        # Try common patterns for chip text retrieval:
        if hasattr(chip, "text"):
            text = chip.text()
        elif hasattr(chip, "_text"):
            text = chip._text
        else:
            text = str(chip)
        assert "Edit" in text and "password" in text.lower(), (
            f"Expected 'Edit' + 'password' in chip text, got: {text!r}")
    finally:
        if saved is not None:
            keyring_core._keyring_backend = saved
