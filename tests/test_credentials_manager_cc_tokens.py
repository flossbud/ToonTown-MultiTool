"""Tests for CredentialsManager CC launcher-token storage."""

import os
import pytest


@pytest.fixture
def cm(tmp_path, monkeypatch):
    """Fresh CredentialsManager pointed at a tmp config dir, with a stubbed
    in-process keyring so we don't touch the user's real keyring."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import keyring
    from keyring.backend import KeyringBackend

    class _MemBackend(KeyringBackend):
        priority = 999
        def __init__(self):
            self._store = {}
        def get_password(self, service, username):
            return self._store.get((service, username))
        def set_password(self, service, username, password):
            self._store[(service, username)] = password
        def delete_password(self, service, username):
            self._store.pop((service, username), None)

    backend = _MemBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "set_keyring", lambda b: None)
    keyring.set_keyring(backend)

    from utils.credentials_manager import CredentialsManager
    return CredentialsManager()


def test_get_launcher_token_returns_empty_when_unset(cm):
    assert cm.get_launcher_token("nonexistent-id") == ""
