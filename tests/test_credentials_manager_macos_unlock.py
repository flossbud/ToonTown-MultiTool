"""Darwin launch-unlock flow + controlled migration (Milestone 4).

These build a real ``CredentialsManager`` on ``darwin`` against a tmp config dir
with a real ``MacOSCredentialVault`` behind it, and drive ``run_probe`` (which on
darwin routes to ``_macos_unlock``). The single biometric gate is mocked by
monkeypatching ``services.macos_biometric_gate.authenticate``; legacy Keychain
reads/writes go through a small in-process recording keyring backend, so NO real
Touch ID and NO real Keychain are ever touched.

Isolation: HOME + TTMT_CONFIG_DIR point at the per-test tmp dir; ``sys.platform``
is pinned to ``darwin`` before construction so ``_init_macos_vault`` runs.
"""

import sys

import pytest
from keyring.backend import KeyringBackend

from utils.build_flavor import keyring_service, cc_token_service
from services.macos_biometric_gate import BiometricResult


class _RecordingBackend(KeyringBackend):
    """In-process keyring that records every call, so a test can assert exactly
    which legacy items the migration read and deleted."""

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


def _make_cm(monkeypatch, tmp_path, *, backend=None):
    """Build a darwin CredentialsManager against ``tmp_path``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("TTMT_MACOS_VAULT", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    if backend is not None:
        import keyring
        import keyring.core
        monkeypatch.setattr(keyring.core, "_keyring_backend", backend, raising=False)
        monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    from utils.credentials_manager import CredentialsManager
    return CredentialsManager()


def _mock_gate(monkeypatch, result, *, counter=None):
    """Monkeypatch the biometric gate's ``authenticate`` to return ``result``.
    If ``counter`` (a dict) is given, bump ``counter['n']`` on each call."""
    import services.macos_biometric_gate as gate_mod

    def _auth(reason=None):
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1
        return result

    monkeypatch.setattr(gate_mod, "authenticate", _auth)


# ── gate SUCCESS -> unlocked ─────────────────────────────────────────────────

def test_gate_success_loads_vault_and_unlocks(monkeypatch, tmp_path):
    from utils.macos_credential_vault import VaultState
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    assert cm.macos_unlock_state == "unlocked"
    assert cm._macos_vault.state == VaultState.LOADED
    assert cm.keyring_available is True


# ── gate CANCELLED / FAILED -> denied, vault NOT loaded ──────────────────────

@pytest.mark.parametrize("result", [BiometricResult.CANCELLED, BiometricResult.FAILED])
def test_gate_denied_leaves_vault_not_loaded(monkeypatch, tmp_path, result):
    from utils.macos_credential_vault import VaultState
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    _mock_gate(monkeypatch, result)

    assert cm.run_probe() is False
    assert cm.macos_unlock_state == "denied"
    assert cm._macos_vault.state == VaultState.NOT_LOADED
    assert cm.keyring_available is False


def test_gate_exception_treated_as_denied(monkeypatch, tmp_path):
    from utils.macos_credential_vault import VaultState
    import services.macos_biometric_gate as gate_mod
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]

    def _boom(reason=None):
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(gate_mod, "authenticate", _boom)

    # The probe worker must never crash: a gate exception is a denied gate.
    assert cm.run_probe() is False
    assert cm.macos_unlock_state == "denied"
    assert cm._macos_vault.state == VaultState.NOT_LOADED


# ── gate UNAVAILABLE -> deliberate fail-open ─────────────────────────────────

def test_gate_unavailable_fails_open(monkeypatch, tmp_path):
    from utils.macos_credential_vault import VaultState
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    _mock_gate(monkeypatch, BiometricResult.UNAVAILABLE)

    assert cm.run_probe() is True
    assert cm.macos_unlock_state == "none"
    assert cm._macos_vault.state == VaultState.LOADED


# ── nothing saved -> gate is NEVER called ────────────────────────────────────

def test_no_secret_skips_gate_entirely(monkeypatch, tmp_path):
    from utils.macos_credential_vault import VaultState
    cm = _make_cm(monkeypatch, tmp_path)
    assert cm._accounts == []          # nothing saved
    assert not (tmp_path / "vault.enc").exists()
    assert not (tmp_path / "vault.key").exists()

    counter = {"n": 0}
    _mock_gate(monkeypatch, BiometricResult.SUCCESS, counter=counter)

    assert cm.run_probe() is True
    assert counter["n"] == 0           # the gate was never invoked
    assert cm.macos_unlock_state == "none"
    assert cm._macos_vault.state == VaultState.LOADED


# ── migration: legacy password -> vault, legacy item deleted ─────────────────

def test_migration_moves_legacy_password_and_deletes_it(monkeypatch, tmp_path):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    # Seed a legacy Keychain password (NOT in the vault).
    backend.store[(keyring_service(), "acc-1")] = "legacy-pw"
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    # The vault now holds the migrated password...
    assert cm._macos_vault.get_password("acc-1") == "legacy-pw"
    # ...and the legacy item was deleted (write-verify-THEN-delete).
    assert ("delete", keyring_service(), "acc-1") in backend.calls
    assert (keyring_service(), "acc-1") not in backend.store


def test_migration_keeps_legacy_when_flag_set(monkeypatch, tmp_path):
    # TTMT_VAULT_KEEP_LEGACY=1: copy into the vault but leave the legacy
    # Keychain item as a recovery fallback (no delete).
    monkeypatch.setenv("TTMT_VAULT_KEEP_LEGACY", "1")
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [{"id": "acc-1", "game": "cc"}]
    backend.store[(keyring_service(), "acc-1")] = "legacy-pw"
    backend.store[(cc_token_service(), "acc-1")] = "legacy-tok"
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    # Copied into the vault...
    assert cm._macos_vault.get_password("acc-1") == "legacy-pw"
    assert cm._macos_vault.get_token("acc-1") == "legacy-tok"
    # ...but the legacy items are NOT deleted (kept as fallback).
    assert ("delete", keyring_service(), "acc-1") not in backend.calls
    assert ("delete", cc_token_service(), "acc-1") not in backend.calls
    assert (keyring_service(), "acc-1") in backend.store
    assert (cc_token_service(), "acc-1") in backend.store


def test_migration_moves_legacy_cc_token_and_deletes_it(monkeypatch, tmp_path):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [{"id": "cc-1", "game": "cc"}]
    backend.store[(keyring_service(), "cc-1")] = "cc-pw"
    backend.store[(cc_token_service(), "cc-1")] = "cc-tok"
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    assert cm._macos_vault.get_password("cc-1") == "cc-pw"
    assert cm._macos_vault.get_token("cc-1") == "cc-tok"
    assert ("delete", keyring_service(), "cc-1") in backend.calls
    assert ("delete", cc_token_service(), "cc-1") in backend.calls


def test_migration_records_known_absent_for_missing_legacy(monkeypatch, tmp_path):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]  # no legacy secret at all
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    # A known-absent (None) marker is stored so we never re-probe it.
    assert cm._macos_vault.has_password("acc-1") is True
    assert cm._macos_vault.get_password("acc-1") == ""
    # Nothing to delete when there was no legacy item.
    assert ("delete", keyring_service(), "acc-1") not in backend.calls


def test_migration_is_idempotent(monkeypatch, tmp_path):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    backend.store[(keyring_service(), "acc-1")] = "legacy-pw"
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    assert cm._macos_vault.get_password("acc-1") == "legacy-pw"

    # Second unlock: the account is already migrated (has_password True), so no
    # further legacy reads or deletes happen.
    backend.calls.clear()
    assert cm.run_probe() is True
    assert ("get", keyring_service(), "acc-1") not in backend.calls
    assert ("delete", keyring_service(), "acc-1") not in backend.calls


# ── write-verify-BEFORE-delete: a refused vault write stops migration ────────

def test_vault_write_error_stops_migration_without_deleting(monkeypatch, tmp_path):
    from utils.macos_credential_vault import VaultError
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [
        {"id": "acc-1", "game": "ttr"},
        {"id": "acc-2", "game": "ttr"},
    ]
    backend.store[(keyring_service(), "acc-1")] = "pw-1"
    backend.store[(keyring_service(), "acc-2")] = "pw-2"
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    # Make the vault refuse the write (as a CORRUPT / KEY_MISSING vault would).
    def _refuse(account_id, password):
        raise VaultError("write refused")

    monkeypatch.setattr(cm._macos_vault, "set_password", _refuse)

    cm.run_probe()
    # The legacy items must survive: no delete was issued for either account.
    assert ("delete", keyring_service(), "acc-1") not in backend.calls
    assert ("delete", keyring_service(), "acc-2") not in backend.calls
    assert backend.store[(keyring_service(), "acc-1")] == "pw-1"
    assert backend.store[(keyring_service(), "acc-2")] == "pw-2"


# ── stamp: migrated count is correct ─────────────────────────────────────────

def test_startup_stamp_migrated_count(monkeypatch, tmp_path, capsys):
    backend = _RecordingBackend()
    cm = _make_cm(monkeypatch, tmp_path, backend=backend)
    cm._accounts = [
        {"id": "acc-1", "game": "ttr"},
        {"id": "acc-2", "game": "ttr"},
        {"id": "acc-3", "game": "ttr"},
    ]
    backend.store[(keyring_service(), "acc-1")] = "pw-1"
    backend.store[(keyring_service(), "acc-2")] = "pw-2"
    # acc-3 has no legacy secret; it still counts as migrated (null marker).
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)

    assert cm.run_probe() is True
    out = capsys.readouterr().out
    assert "[Vault] mode=adhoc-keyfile accounts=3 unlock=gate migrated=3" in out


def test_startup_stamp_no_secret(monkeypatch, tmp_path, capsys):
    cm = _make_cm(monkeypatch, tmp_path)
    _mock_gate(monkeypatch, BiometricResult.SUCCESS)
    assert cm.run_probe() is True
    out = capsys.readouterr().out
    assert "[Vault] mode=adhoc-keyfile accounts=0 unlock=none migrated=0" in out


def test_startup_stamp_denied(monkeypatch, tmp_path, capsys):
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]
    _mock_gate(monkeypatch, BiometricResult.CANCELLED)
    assert cm.run_probe() is False
    out = capsys.readouterr().out
    assert "[Vault] mode=adhoc-keyfile accounts=1 unlock=denied migrated=0" in out


# ── default state + re-gate path ─────────────────────────────────────────────

def test_unlock_state_starts_pending(monkeypatch, tmp_path):
    cm = _make_cm(monkeypatch, tmp_path)
    assert cm.macos_unlock_state == "pending"


def test_denied_then_re_probe_unlocks(monkeypatch, tmp_path):
    # The UI re-triggers a gate simply by re-running run_probe on the worker.
    import services.macos_biometric_gate as gate_mod
    cm = _make_cm(monkeypatch, tmp_path)
    cm._accounts = [{"id": "acc-1", "game": "ttr"}]

    monkeypatch.setattr(gate_mod, "authenticate", lambda reason=None: BiometricResult.CANCELLED)
    assert cm.run_probe() is False
    assert cm.macos_unlock_state == "denied"

    monkeypatch.setattr(gate_mod, "authenticate", lambda reason=None: BiometricResult.SUCCESS)
    assert cm.run_probe() is True
    assert cm.macos_unlock_state == "unlocked"
