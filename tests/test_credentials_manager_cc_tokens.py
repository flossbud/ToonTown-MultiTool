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
    # ``keyring.get_password`` / ``set_password`` / ``delete_password`` live in
    # ``keyring.core`` and resolve ``get_keyring()`` against that module's
    # globals, so patching ``keyring.get_keyring`` alone isn't enough — we
    # have to install the backend via the real ``set_keyring`` and unwind it
    # in a finalizer. We still patch the public alias so any caller reading
    # ``keyring.get_keyring()`` directly sees the same backend.
    import keyring.core
    prev = keyring.core._keyring_backend
    keyring.set_keyring(backend)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)

    from utils.credentials_manager import CredentialsManager
    cm = CredentialsManager()
    # _try_keyring_call gates non-(get|set)_password through _probe_complete.
    # The probe is normally run from a background thread on app start; for
    # these unit tests we mark it complete directly so delete_password can
    # flow through the same code path as in production.
    cm._probe_complete = True
    cm._use_keyring = True
    yield cm
    # Restore whatever backend was selected before this test.
    keyring.core._keyring_backend = prev


def test_get_launcher_token_returns_empty_when_unset(cm):
    assert cm.get_launcher_token("nonexistent-id") == ""


def test_set_and_get_launcher_token_round_trip(cm):
    cm.set_launcher_token("abc-id", "tok-123")
    assert cm.get_launcher_token("abc-id") == "tok-123"


def test_set_launcher_token_overwrites(cm):
    cm.set_launcher_token("abc-id", "tok-1")
    cm.set_launcher_token("abc-id", "tok-2")
    assert cm.get_launcher_token("abc-id") == "tok-2"


def test_clear_launcher_token_removes_entry(cm):
    cm.set_launcher_token("abc-id", "tok-x")
    cm.clear_launcher_token("abc-id")
    assert cm.get_launcher_token("abc-id") == ""


def test_clear_launcher_token_noop_when_absent(cm):
    # Should not raise.
    cm.clear_launcher_token("never-existed")
    assert cm.get_launcher_token("never-existed") == ""
