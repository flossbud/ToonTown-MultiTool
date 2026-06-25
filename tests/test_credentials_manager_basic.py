"""get_accounts_basic: keyring-free account essentials for hot GUI paths."""
import os

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest


@pytest.fixture
def cm_spy(tmp_path, monkeypatch):
    """CredentialsManager pointed at a tmp config dir with an in-process keyring
    backend that COUNTS get_password calls, so a test can assert zero reads."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import keyring
    from keyring.backend import KeyringBackend

    class _CountingBackend(KeyringBackend):
        priority = 999
        def __init__(self):
            self.get_calls = 0
            self._store = {}
        def get_password(self, service, username):
            self.get_calls += 1
            return self._store.get((service, username))
        def set_password(self, service, username, password):
            self._store[(service, username)] = password
        def delete_password(self, service, username):
            self._store.pop((service, username), None)

    backend = _CountingBackend()
    import keyring.core
    prev = keyring.core._keyring_backend
    keyring.set_keyring(backend)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    from utils.credentials_manager import CredentialsManager
    cm = CredentialsManager()
    cm._probe_complete = True
    cm._use_keyring = True
    yield cm, backend
    keyring.core._keyring_backend = prev


def test_get_accounts_basic_returns_id_game_label_no_keyring(cm_spy):
    cm, backend = cm_spy
    cm._accounts = [
        {"id": "a1", "game": "ttr", "label": "Main", "username": "u1"},
        {"id": "a2", "game": "cc", "label": "", "username": "u2"},   # blank label -> username
        {"id": "a3", "game": "ttr", "username": "u3"},               # no label key -> username
    ]
    before = backend.get_calls
    basic = cm.get_accounts_basic()
    assert basic == [("a1", "ttr", "Main"), ("a2", "cc", "u2"), ("a3", "ttr", "u3")]
    assert backend.get_calls == before          # ZERO keyring reads


def test_get_accounts_basic_filters_by_game(cm_spy):
    cm, backend = cm_spy
    cm._accounts = [
        {"id": "a1", "game": "ttr", "username": "u1"},
        {"id": "a2", "game": "cc", "username": "u2"},
    ]
    assert cm.get_accounts_basic(game="cc") == [("a2", "cc", "u2")]


def test_get_accounts_basic_skips_idless_entries(cm_spy):
    cm, backend = cm_spy
    cm._accounts = [
        {"game": "ttr", "username": "noid"},        # missing id -> skipped
        {"id": "a2", "game": "ttr", "username": "u2"},
    ]
    assert [b[0] for b in cm.get_accounts_basic()] == ["a2"]
