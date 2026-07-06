"""Offscreen unit tests for the macOS app-encrypted credential vault.

No real Keychain, no network, no Qt. Config is isolated to a per-test tmp dir
via HOME + TTMT_CONFIG_DIR set BEFORE the vault is constructed (the vault reads
config_dir() at construction, and config_dir() honours TTMT_CONFIG_DIR), so
nothing here can touch the developer's real credential files.
"""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.macos_credential_vault import (
    MacOSCredentialVault,
    VaultError,
    VaultState,
)


@pytest.fixture
def vault_dir(tmp_path, monkeypatch):
    """Isolate config to a tmp dir before any vault is built (IRON LAW)."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(cfg))
    return cfg


@pytest.fixture
def vault(vault_dir):
    return MacOSCredentialVault()


def _read_header(vault_dir):
    with open(os.path.join(str(vault_dir), "vault.enc"), "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _write_enc(vault_dir, header: dict):
    with open(os.path.join(str(vault_dir), "vault.enc"), "wb") as f:
        f.write(json.dumps(header).encode("utf-8"))


# ── Fresh install + round-trip ──────────────────────────────────────────────

def test_fresh_install_creates_key_and_ciphertext(vault, vault_dir):
    assert not os.path.exists(vault_dir / "vault.enc")
    assert not os.path.exists(vault_dir / "vault.key")

    assert vault.load() == VaultState.LOADED
    assert vault.is_loaded
    # A fresh load persists nothing until the first write.
    assert not os.path.exists(vault_dir / "vault.enc")

    vault.set_password("acct-1", "hunter2")

    assert os.path.exists(vault_dir / "vault.enc")
    assert os.path.exists(vault_dir / "vault.key")
    # 0600 on both files.
    assert (os.stat(vault_dir / "vault.enc").st_mode & 0o777) == 0o600
    assert (os.stat(vault_dir / "vault.key").st_mode & 0o777) == 0o600
    # Master key is a raw 256-bit value.
    assert os.path.getsize(vault_dir / "vault.key") == 32


def test_password_round_trip_across_instances(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "pw-a")
    v1.set_password("b", "pw-b")

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.LOADED
    assert v2.get_password("a") == "pw-a"
    assert v2.get_password("b") == "pw-b"
    assert v2.get_password("missing") == ""


def test_token_round_trip_across_instances(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_token("cc-1", "tok-xyz")

    v2 = MacOSCredentialVault()
    v2.load()
    assert v2.get_token("cc-1") == "tok-xyz"
    assert v2.get_token("cc-none") == ""


def test_passwords_and_tokens_are_separate_namespaces(vault):
    vault.set_password("shared-id", "the-password")
    vault.set_token("shared-id", "the-token")
    assert vault.get_password("shared-id") == "the-password"
    assert vault.get_token("shared-id") == "the-token"


# ── rev increments + fresh nonce per write ──────────────────────────────────

def test_rev_increments_per_write(vault, vault_dir):
    vault.set_password("a", "1")
    assert _read_header(vault_dir)["rev"] == 1
    vault.set_password("b", "2")
    assert _read_header(vault_dir)["rev"] == 2
    vault.set_token("a", "t")
    assert _read_header(vault_dir)["rev"] == 3


def test_fresh_nonce_per_write(vault, vault_dir):
    vault.set_password("a", "1")
    nonce1 = _read_header(vault_dir)["nonce"]
    vault.set_password("a", "1")  # same value, still a distinct write
    nonce2 = _read_header(vault_dir)["nonce"]
    assert nonce1 != nonce2
    # Nonce is a fresh 12-byte value each time.
    assert len(base64.b64decode(nonce1)) == 12
    assert len(base64.b64decode(nonce2)) == 12


# ── AAD / tamper rejection (fail closed, never a silent empty vault) ─────────

def test_flipped_ciphertext_byte_is_corrupt_not_empty(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")

    header = _read_header(vault_dir)
    ct = bytearray(base64.b64decode(header["ct"]))
    ct[0] ^= 0x01  # flip a bit in the ciphertext/tag
    header["ct"] = base64.b64encode(bytes(ct)).decode("ascii")
    _write_enc(vault_dir, header)

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.CORRUPT
    assert not v2.is_loaded
    # Fail closed: no silent empty vault.
    assert v2.get_password("a") == ""


def test_tampered_header_rev_fails_aad(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")

    header = _read_header(vault_dir)
    header["rev"] = header["rev"] + 999  # rev is bound into the AAD
    _write_enc(vault_dir, header)

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.CORRUPT


def test_garbage_file_is_corrupt(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")
    with open(vault_dir / "vault.enc", "wb") as f:
        f.write(b"not json at all")

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.CORRUPT


# ── Atomic write leaves a valid, re-loadable file ───────────────────────────

def test_atomic_write_leaves_valid_file_and_no_temp(vault, vault_dir):
    vault.set_password("a", "1")
    vault.set_password("b", "2")
    # No leftover temp files from the atomic replace.
    leftovers = [p for p in os.listdir(str(vault_dir)) if p.endswith(".tmp")]
    assert leftovers == []
    # The file decrypts cleanly in a fresh instance.
    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.LOADED
    assert v2.get_password("a") == "1"
    assert v2.get_password("b") == "2"


# ── .bak restore path ───────────────────────────────────────────────────────

def test_bak_restore_when_enc_corrupt_but_bak_good(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "v1-secret")   # first write: enc only, no .bak yet
    v1.set_password("a", "v2-secret")   # second write: enc=rev2, .bak=rev1

    assert os.path.exists(vault_dir / "vault.enc.bak")

    # Corrupt the live ciphertext; leave the (good) backup intact.
    header = _read_header(vault_dir)
    ct = bytearray(base64.b64decode(header["ct"]))
    ct[0] ^= 0xFF
    header["ct"] = base64.b64encode(bytes(ct)).decode("ascii")
    _write_enc(vault_dir, header)

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.LOADED
    # Restored to the previous good revision's contents.
    assert v2.get_password("a") == "v1-secret"
    # The restore rewrote vault.enc so it now authenticates on its own.
    v3 = MacOSCredentialVault()
    assert v3.load() == VaultState.LOADED
    assert v3.get_password("a") == "v1-secret"


# ── Missing key over an existing vault => KEY_MISSING, no silent regen ───────

def test_missing_key_over_existing_enc_is_key_missing(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")
    assert os.path.exists(vault_dir / "vault.key")

    os.remove(vault_dir / "vault.key")

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.KEY_MISSING
    assert not v2.is_loaded
    assert v2.get_password("a") == ""
    # A write must NOT silently regenerate the key + orphan the ciphertext.
    with pytest.raises(VaultError):
        v2.set_password("a", "new")
    assert not os.path.exists(vault_dir / "vault.key")


def test_corrupt_vault_refuses_writes(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")
    with open(vault_dir / "vault.enc", "wb") as f:
        f.write(b"garbage")

    v2 = MacOSCredentialVault()
    assert v2.load() == VaultState.CORRUPT
    with pytest.raises(VaultError):
        v2.set_password("a", "new")


# ── None (known-no-secret) vs '' semantics ──────────────────────────────────

def test_none_known_absent_vs_missing(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("known-absent", None)   # migrated, known to have no secret
    # Never touched: "not-set" stays absent.

    v2 = MacOSCredentialVault()
    v2.load()
    # Both read back as '' ...
    assert v2.get_password("known-absent") == ""
    assert v2.get_password("not-set") == ""
    # ... but presence-of-key distinguishes them.
    assert v2.has_password("known-absent") is True
    assert v2.has_password("not-set") is False


def test_empty_string_is_stored_and_present(vault):
    vault.set_password("blank", "")
    assert vault.get_password("blank") == ""
    assert vault.has_password("blank") is True


def test_token_none_known_absent_vs_missing(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_token("known-absent", None)

    v2 = MacOSCredentialVault()
    v2.load()
    assert v2.get_token("known-absent") == ""
    assert v2.has_token("known-absent") is True
    assert v2.has_token("never") is False


# ── delete / clear ──────────────────────────────────────────────────────────

def test_delete_password_removes_entry(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")
    assert v1.has_password("a") is True
    v1.delete_password("a")
    assert v1.has_password("a") is False
    assert v1.get_password("a") == ""

    v2 = MacOSCredentialVault()
    v2.load()
    assert v2.has_password("a") is False


def test_clear_token_removes_entry(vault_dir):
    v1 = MacOSCredentialVault()
    v1.set_token("cc-1", "tok")
    assert v1.has_token("cc-1") is True
    v1.clear_token("cc-1")
    assert v1.has_token("cc-1") is False

    v2 = MacOSCredentialVault()
    v2.load()
    assert v2.has_token("cc-1") is False


def test_delete_absent_is_noop_no_rev_bump(vault, vault_dir):
    vault.set_password("a", "1")
    rev_before = _read_header(vault_dir)["rev"]
    vault.delete_password("does-not-exist")
    # No write happened, so rev is unchanged.
    assert _read_header(vault_dir)["rev"] == rev_before


# ── Data-protection seam is a clean NotImplementedError when forced capable ──

def test_dp_seam_raises_when_forced_capable_on_read(vault_dir, monkeypatch):
    # A vault.enc exists, so load() must read the master key -> DP branch.
    v1 = MacOSCredentialVault()
    v1.set_password("a", "secret")

    v2 = MacOSCredentialVault()
    monkeypatch.setattr(v2, "_is_data_protection_capable", lambda: True)
    with pytest.raises(NotImplementedError):
        v2.load()


def test_dp_seam_raises_when_forced_capable_on_write(vault, monkeypatch):
    # Fresh vault: first write generates + persists a key -> DP write branch.
    vault.load()
    monkeypatch.setattr(vault, "_is_data_protection_capable", lambda: True)
    with pytest.raises(NotImplementedError):
        vault.set_password("a", "secret")


# ── Import has no side effects ───────────────────────────────────────────────

def test_import_creates_no_files(vault_dir):
    # Importing the module (already done at top) must not have created any
    # vault files in the isolated config dir.
    assert not os.path.exists(vault_dir / "vault.enc")
    assert not os.path.exists(vault_dir / "vault.key")
