"""Darwin credential-vault routing for CredentialsManager (Milestone 3).

These tests pin ``sys.platform`` explicitly and build a real
``CredentialsManager`` against a tmp config dir with a real
``MacOSCredentialVault`` behind it, so the darwin routing is exercised
end-to-end. The cross-platform invariant is proven directly: on
``linux`` / ``win32`` no vault is constructed and the existing keyring path
is used unchanged.

Isolation: HOME + TTMT_CONFIG_DIR point at the per-test tmp dir; the keyring
is a small in-process recording backend so no real Keychain / Secret Service
is ever touched.
"""

import sys

import pytest
from keyring.backend import KeyringBackend

from utils.build_flavor import keyring_service


class _RecordingBackend(KeyringBackend):
    """In-process keyring that records every call, so a test can assert the
    darwin path never touches the keyring at all."""

    priority = 999

    def __init__(self):
        self.store = {}
        self.calls = []

    def get_password(self, service, username):
        self.calls.append(("get", service, username))
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.calls.append(("set", service, username, password))
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        self.store.pop((service, username), None)


def _make_cm(monkeypatch, tmp_path, platform, *, kill_switch=False, backend=None):
    """Build a CredentialsManager for ``platform`` against ``tmp_path``.

    Env + ``sys.platform`` are set BEFORE construction so ``_init_macos_vault``
    (which runs in ``__init__``) sees the intended platform / kill-switch state.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    if kill_switch:
        monkeypatch.setenv("TTMT_MACOS_VAULT", "0")
    else:
        monkeypatch.delenv("TTMT_MACOS_VAULT", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    if backend is not None:
        import keyring
        import keyring.core
        monkeypatch.setattr(keyring.core, "_keyring_backend", backend, raising=False)
        monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    from utils.credentials_manager import CredentialsManager
    return CredentialsManager()


# ── darwin: passwords route through the vault ────────────────────────────────

def test_darwin_password_round_trips_through_vault(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", backend=backend)
    assert cm._macos_vault is not None
    assert cm._macos_vault_fallback is None

    assert cm._set_password("acc-1", "s3cret") is True
    assert cm._get_password("acc-1") == "s3cret"

    # Persisted to the encrypted vault, and a fresh vault instance sees it.
    assert (tmp_path / "vault.enc").exists()
    assert MacOSCredentialVault().get_password("acc-1") == "s3cret"
    # The keyring was never touched on darwin.
    assert backend.calls == []


def test_darwin_token_round_trips_through_vault(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", backend=backend)

    cm.set_launcher_token("acc-1", "tok-abc")
    assert cm.get_launcher_token("acc-1") == "tok-abc"

    assert MacOSCredentialVault().get_token("acc-1") == "tok-abc"
    assert backend.calls == []


def test_darwin_get_accounts_returns_vault_passwords(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", backend=backend)

    assert cm.add_account(label="Main", username="user1", password="pw1", game="ttr") is True
    accts = cm.get_accounts()
    assert len(accts) == 1
    assert accts[0].password == "pw1"

    aid = cm._accounts[0]["id"]
    assert MacOSCredentialVault().get_password(aid) == "pw1"
    assert backend.calls == []


def test_darwin_delete_password_removes_from_vault(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    cm = _make_cm(monkeypatch, tmp_path, "darwin")

    cm._set_password("acc-del", "temp")
    assert MacOSCredentialVault().get_password("acc-del") == "temp"

    cm._delete_password("acc-del")
    assert MacOSCredentialVault().has_password("acc-del") is False


# ── darwin: availability tracks vault state ──────────────────────────────────

def test_darwin_probe_pending_then_available(monkeypatch, tmp_path):
    cm = _make_cm(monkeypatch, tmp_path, "darwin")
    # Vault not loaded yet.
    assert cm.keyring_probe_pending is True
    assert cm.keyring_available is False

    assert cm.run_probe() is True  # loads the vault (no biometric gate here)

    assert cm.keyring_available is True
    assert cm.keyring_probe_pending is False


# ── may-a-secret-exist gate decision ─────────────────────────────────────────

def test_macos_secret_may_exist(monkeypatch, tmp_path):
    cm = _make_cm(monkeypatch, tmp_path, "darwin")
    # Nothing saved: no accounts, no vault files.
    assert cm.macos_secret_may_exist() is False

    # An account drives it true.
    cm._accounts.append({"id": "a", "game": "ttr"})
    assert cm.macos_secret_may_exist() is True

    # A stray vault file (no accounts) also drives it true.
    cm._accounts.clear()
    assert cm.macos_secret_may_exist() is False
    (tmp_path / "vault.key").write_bytes(b"\x00" * 32)
    assert cm.macos_secret_may_exist() is True


def test_non_darwin_secret_may_exist_ignores_vault_files(monkeypatch, tmp_path):
    # A stray vault file on Linux/Windows must NOT count as a secret.
    cm = _make_cm(monkeypatch, tmp_path, "linux")
    (tmp_path / "vault.enc").write_bytes(b"junk")
    assert cm.macos_secret_may_exist() is False
    cm._accounts.append({"id": "a", "game": "ttr"})
    assert cm.macos_secret_may_exist() is True


# ── kill switch: legacy writes, vault read-fallback ──────────────────────────

def test_kill_switch_set_password_uses_legacy_not_vault(monkeypatch, tmp_path):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", kill_switch=True, backend=backend)
    cm._probe_complete = True
    cm._use_keyring = True
    assert cm._macos_vault is None
    assert cm._macos_vault_fallback is not None

    assert cm._set_password("acc-legacy", "legacy-pw") is True
    # The legacy keyring got the write...
    assert backend.store.get((keyring_service(), "acc-legacy")) == "legacy-pw"
    # ...and nothing was written to the vault.
    assert not (tmp_path / "vault.enc").exists()


def test_kill_switch_get_password_falls_back_to_vault(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    # Pre-seed the vault as if a prior vault-mode run had already migrated.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    seed = MacOSCredentialVault()
    seed.load()
    seed.set_password("seed-acc", "seed-pw")
    assert (tmp_path / "vault.enc").exists()

    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", kill_switch=True, backend=backend)
    assert cm._macos_vault is None
    assert cm._macos_vault_fallback is not None

    # Legacy keyring read is empty -> kill-switch fallback recovers from vault.
    assert cm._get_password("seed-acc") == "seed-pw"


def test_kill_switch_get_token_falls_back_to_vault(monkeypatch, tmp_path):
    from utils.macos_credential_vault import MacOSCredentialVault
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    seed = MacOSCredentialVault()
    seed.load()
    seed.set_token("seed-cc", "seed-tok")

    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, "darwin", kill_switch=True, backend=backend)
    assert cm.get_launcher_token("seed-cc") == "seed-tok"


# ── non-darwin: Linux/Windows untouched ──────────────────────────────────────

@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_non_darwin_no_vault_and_uses_keyring(monkeypatch, tmp_path, platform):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, platform, backend=backend)
    # No vault is ever constructed off darwin.
    assert cm._macos_vault is None
    assert cm._macos_vault_fallback is None
    assert cm._VaultState is None

    cm._probe_complete = True
    cm._use_keyring = True
    assert cm._set_password("acc-x", "px") is True
    assert cm._get_password("acc-x") == "px"

    # The secret lives in the keyring, and no vault file was created.
    assert backend.store.get((keyring_service(), "acc-x")) == "px"
    assert not (tmp_path / "vault.enc").exists()
    assert not (tmp_path / "vault.key").exists()


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_non_darwin_token_uses_keyring(monkeypatch, tmp_path, platform):
    from utils.build_flavor import cc_token_service
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, platform, backend=backend)
    cm._probe_complete = True
    cm._use_keyring = True

    cm.set_launcher_token("cc-x", "tok-x")
    assert cm.get_launcher_token("cc-x") == "tok-x"
    assert backend.store.get((cc_token_service(), "cc-x")) == "tok-x"
    assert not (tmp_path / "vault.enc").exists()
