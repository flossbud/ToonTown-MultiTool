"""App-encrypted file vault for macOS credentials.

On macOS the per-account Keychain items re-prompt on every reboot and every
new app version, because the app is ad-hoc signed (its code identity changes
each build) and every Keychain item carries its own ACL. This module replaces
the Keychain in the ad-hoc password path with a single app-encrypted file so
the only credential moment is one Touch ID / password gate at launch (that gate
lives in a separate module; this store is deliberately gate-agnostic).

Storage is two tight-permissioned (``0600``) files in the channel-aware
``config_dir()``:

- ``vault.enc`` - AES-256-GCM ciphertext of the versioned plaintext JSON, with a
  plaintext-readable header ``{"fmt", "nonce", "rev", "ct"}``. The plaintext is
  ``{"v":1, "rev":N, "passwords":{...}, "cc_tokens":{...}}``.
- ``vault.key`` - the raw 256-bit master key (ad-hoc path only). On a future
  signed build the key moves into the data-protection Keychain behind the same
  seam; the ``vault.enc`` format is identical across both modes.

This module is pure stdlib + ``cryptography`` + ``utils.build_flavor.config_dir``.
It imports with zero side effects and has no Qt / keyring / input-service
dependency. Biometrics, session-state routing, and legacy migration live in
other modules (later milestones); this file only owns encrypt / decrypt / atomic
persistence of the vault.
"""

from __future__ import annotations

import base64
import enum
import json
import os
import shutil
import tempfile
import threading

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from utils.build_flavor import config_dir

# On-disk format version for vault.enc's header. Bump only on an incompatible
# layout change; the value is bound into the GCM AAD so a mismatched header
# fails authentication.
_FMT_VERSION = 1

# Plaintext model version (the "v" field inside the decrypted JSON).
_PLAINTEXT_VERSION = 1

_KEY_LEN = 32   # AES-256
_NONCE_LEN = 12  # 96-bit GCM nonce


def _dbg(msg: str) -> None:
    """Opt-in diagnostic. Quiet unless ``TTMT_VAULT_TRACE`` is set, so import
    and normal operation have no side effects. Never raises."""
    if os.environ.get("TTMT_VAULT_TRACE"):
        try:
            print(msg)
        except Exception:
            pass


class VaultState(str, enum.Enum):
    """Coarse load state. The richer session-state model (AUTH_DENIED etc.)
    belongs to the CredentialsManager routing milestone, not here."""

    NOT_LOADED = "NOT_LOADED"
    LOADED = "LOADED"
    CORRUPT = "CORRUPT"
    KEY_MISSING = "KEY_MISSING"


class VaultError(RuntimeError):
    """Raised when a destructive operation is refused because the vault is not
    in a safe (LOADED) state, or when a write fails to verify."""


class MacOSCredentialVault:
    """Owns the two vault files and the in-memory decrypted copy.

    All public methods are synchronous and serialized under one re-entrant
    lock. The decrypted plaintext exists in memory only; it is never written
    to disk unencrypted.
    """

    def __init__(self, vault_dir: str | None = None):
        # config_dir() honours TTMT_CONFIG_DIR, so tests point it at a tmp dir.
        # Resolved at construction (not import) so the env override is live.
        self._dir = vault_dir if vault_dir is not None else config_dir()
        self._enc_path = os.path.join(self._dir, "vault.enc")
        self._key_path = os.path.join(self._dir, "vault.key")
        self._bak_path = self._enc_path + ".bak"
        self._lock = threading.RLock()
        self._state = VaultState.NOT_LOADED
        self._data: dict | None = None   # decrypted plaintext, None unless LOADED
        self._key: bytes | None = None   # master key, cached after load

    # ── Public state ────────────────────────────────────────────────────────

    @property
    def state(self) -> VaultState:
        with self._lock:
            return self._state

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._state == VaultState.LOADED

    # ── Load / unlock ───────────────────────────────────────────────────────

    def load(self) -> VaultState:
        """Read the key + ciphertext and populate the in-memory copy.

        Does NOT perform any biometric / LAContext gate - that is the caller's
        job in a separate module. Returns the resulting :class:`VaultState`.
        """
        with self._lock:
            return self._load_locked()

    # Alias: callers may prefer the unlock verb even though this store does no
    # biometrics itself.
    def unlock(self) -> VaultState:
        return self.load()

    def _load_locked(self) -> VaultState:
        enc_exists = os.path.exists(self._enc_path)
        key = self._read_master_key()  # None if absent / unreadable / malformed

        if not enc_exists:
            # No ciphertext on disk. Try to recover from a stray last-good
            # backup if we can (enc deleted but .bak + key survived); else this
            # is a fresh install and the first write will create everything.
            if key is not None and os.path.exists(self._bak_path):
                recovered = self._try_decrypt_file(self._bak_path, key)
                if recovered is not None:
                    self._restore_enc_from_bak()
                    self._key = key
                    self._data = recovered
                    self._state = VaultState.LOADED
                    _dbg("[Vault] load: recovered from .bak (enc missing)")
                    return self._state
            self._key = key  # may be None; first write will generate one
            self._data = self._empty_data()
            self._state = VaultState.LOADED
            _dbg("[Vault] load: fresh (no vault.enc)")
            return self._state

        # vault.enc exists.
        if key is None:
            # Never silently regenerate the key over an existing ciphertext:
            # that would orphan every secret. This is a locked / recovery state.
            self._key = None
            self._data = None
            self._state = VaultState.KEY_MISSING
            _dbg("[Vault] load: KEY_MISSING (vault.enc present, key absent/unreadable)")
            return self._state

        data = self._try_decrypt_file(self._enc_path, key)
        if data is not None:
            self._key = key
            self._data = data
            self._state = VaultState.LOADED
            _dbg(f"[Vault] load: LOADED rev={data.get('rev')}")
            return self._state

        # vault.enc failed to authenticate. Try the last-good backup before
        # giving up; only restore if the backup itself authenticates.
        if os.path.exists(self._bak_path):
            bak = self._try_decrypt_file(self._bak_path, key)
            if bak is not None:
                self._restore_enc_from_bak()
                self._key = key
                self._data = bak
                self._state = VaultState.LOADED
                _dbg("[Vault] load: restored from .bak (vault.enc corrupt)")
                return self._state

        # Corrupt and unrecoverable. Preserve the raw file; halt destructive ops.
        self._key = key
        self._data = None
        self._state = VaultState.CORRUPT
        _dbg("[Vault] load: CORRUPT (vault.enc failed auth, no good .bak)")
        return self._state

    # ── Password accessors ──────────────────────────────────────────────────

    def get_password(self, account_id: str) -> str:
        """Return the stored password, or '' if absent, known-absent (None),
        or the vault is not in a readable state."""
        with self._lock:
            self._ensure_loaded_readonly()
            if self._data is None:
                return ""
            val = self._data["passwords"].get(account_id)
            return val or ""

    def has_password(self, account_id: str) -> bool:
        """True if the account has a key in ``passwords`` (even a ``None``
        known-absent marker). Distinguishes 'known, no secret' from 'not
        present' - the presence-of-key semantics migration relies on."""
        with self._lock:
            self._ensure_loaded_readonly()
            return self._data is not None and account_id in self._data["passwords"]

    def set_password(self, account_id: str, password: str | None) -> None:
        """Store ``password`` for the account (a string, or ``None`` to record a
        known-no-secret marker). Bumps ``rev`` and re-encrypts the whole vault."""
        if not account_id:
            return
        with self._lock:
            self._ensure_loaded_for_write()
            self._data["passwords"][account_id] = password
            self._persist()

    def delete_password(self, account_id: str) -> None:
        """Remove the account's password entry entirely (not present)."""
        if not account_id:
            return
        with self._lock:
            self._ensure_loaded_for_write()
            if account_id in self._data["passwords"]:
                del self._data["passwords"][account_id]
                self._persist()

    # ── CC launcher-token accessors ─────────────────────────────────────────

    def get_token(self, account_id: str) -> str:
        """Return the stored CC launcher token, or '' if absent / known-absent /
        vault not readable."""
        with self._lock:
            self._ensure_loaded_readonly()
            if self._data is None:
                return ""
            val = self._data["cc_tokens"].get(account_id)
            return val or ""

    def has_token(self, account_id: str) -> bool:
        """True if the account has a key in ``cc_tokens`` (even ``None``)."""
        with self._lock:
            self._ensure_loaded_readonly()
            return self._data is not None and account_id in self._data["cc_tokens"]

    def set_token(self, account_id: str, token: str | None) -> None:
        """Store a CC launcher token (or ``None`` for a known-absent marker)."""
        if not account_id:
            return
        with self._lock:
            self._ensure_loaded_for_write()
            self._data["cc_tokens"][account_id] = token
            self._persist()

    def clear_token(self, account_id: str) -> None:
        """Remove the account's CC launcher-token entry entirely."""
        if not account_id:
            return
        with self._lock:
            self._ensure_loaded_for_write()
            if account_id in self._data["cc_tokens"]:
                del self._data["cc_tokens"][account_id]
                self._persist()

    # ── Load-state guards ───────────────────────────────────────────────────

    def _ensure_loaded_readonly(self) -> None:
        """Lazily load for a read. Any non-LOADED result leaves ``_data`` None
        and read accessors degrade to '' - reads never mutate the store."""
        if self._state == VaultState.NOT_LOADED:
            self._load_locked()

    def _ensure_loaded_for_write(self) -> None:
        """Lazily load, then refuse the write unless the vault is LOADED.

        A CORRUPT or KEY_MISSING vault must never be overwritten (that would
        destroy recoverable data or orphan secrets), so writes raise here.
        """
        if self._state == VaultState.NOT_LOADED:
            self._load_locked()
        if self._state != VaultState.LOADED or self._data is None:
            raise VaultError(
                f"vault not writable in state {self._state.value}; "
                "refusing to overwrite (would lose or orphan data)"
            )

    @staticmethod
    def _empty_data() -> dict:
        return {"v": _PLAINTEXT_VERSION, "rev": 0, "passwords": {}, "cc_tokens": {}}

    # ── Crypto ──────────────────────────────────────────────────────────────

    @staticmethod
    def _aad(fmt: int, rev: int) -> bytes:
        """Additional authenticated data binding the format version and rev into
        the GCM tag. A rolled-back or swapped ciphertext whose header rev is
        edited to a different value produces a different AAD and fails to
        authenticate."""
        return f"ttmt-vault:fmt={int(fmt)}:rev={int(rev)}".encode("ascii")

    def _encrypt_blob(self, data: dict, key: bytes) -> bytes:
        """Serialize + encrypt ``data`` into the on-disk ``vault.enc`` bytes.
        A fresh random nonce is drawn on every call (never reused)."""
        rev = int(data["rev"])
        nonce = os.urandom(_NONCE_LEN)
        plaintext = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        aad = self._aad(_FMT_VERSION, rev)
        ct = AESGCM(key).encrypt(nonce, plaintext, aad)
        header = {
            "fmt": _FMT_VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "rev": rev,
            "ct": base64.b64encode(ct).decode("ascii"),
        }
        return json.dumps(header, separators=(",", ":")).encode("utf-8")

    def _try_decrypt_file(self, path: str, key: bytes) -> dict | None:
        """Read + authenticate + parse a vault ciphertext file. Returns the
        plaintext dict, or ``None`` on any parse failure or failed tag
        (fail-closed: a tampered or corrupt file is never a silent empty
        vault)."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            header = json.loads(raw.decode("utf-8"))
            fmt = int(header["fmt"])
            nonce = base64.b64decode(header["nonce"])
            rev = int(header["rev"])
            ct = base64.b64decode(header["ct"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            _dbg(f"[Vault] decrypt: header parse failed for {os.path.basename(path)}: {type(e).__name__}")
            return None
        try:
            aad = self._aad(fmt, rev)
            plaintext = AESGCM(key).decrypt(nonce, ct, aad)
            data = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, json.JSONDecodeError) as e:
            _dbg(f"[Vault] decrypt: auth/parse failed for {os.path.basename(path)}: {type(e).__name__}")
            return None
        # Structural sanity + header/plaintext rev agreement (belt-and-suspenders;
        # the AAD already binds the header rev to the ciphertext).
        if not isinstance(data, dict):
            return None
        if int(data.get("rev", -1)) != rev:
            _dbg("[Vault] decrypt: header/plaintext rev mismatch")
            return None
        if not isinstance(data.get("passwords"), dict) or not isinstance(data.get("cc_tokens"), dict):
            _dbg("[Vault] decrypt: unexpected plaintext shape")
            return None
        return data

    # ── Persistence ─────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Re-encrypt the whole in-memory vault and write it atomically.

        Bumps ``rev``; keeps the previous good ciphertext as ``vault.enc.bak``;
        reads the new file back and re-decrypts it before trusting the write.
        Caller must hold the lock and have verified LOADED state.
        """
        # Be self-sufficient about the config dir: in the integrated flow
        # CredentialsManager creates it, but the vault must not crash if used
        # standalone before that (mkstemp would fail on a missing dir).
        os.makedirs(self._dir, exist_ok=True)

        if self._key is None:
            self._key = self._generate_and_store_key()

        new_rev = int(self._data.get("rev", 0)) + 1
        self._data["rev"] = new_rev
        blob = self._encrypt_blob(self._data, self._key)

        # Preserve the current good ciphertext as the last-good backup BEFORE we
        # overwrite it, so a failed/interrupted write can roll back.
        if os.path.exists(self._enc_path):
            try:
                shutil.copy2(self._enc_path, self._bak_path)
                os.chmod(self._bak_path, 0o600)
            except OSError as e:
                _dbg(f"[Vault] persist: could not refresh .bak: {type(e).__name__}")

        self._atomic_write(self._enc_path, blob)

        # Read-back verify: the freshly written file must decrypt and carry the
        # rev we just wrote. Anything else means either a bad write or an
        # external clobber.
        verify = self._try_decrypt_file(self._enc_path, self._key)
        if verify is None:
            # Our own write did not read back cleanly. Roll back to .bak if it
            # authenticates, then surface the failure - never trust the state.
            restored = False
            if os.path.exists(self._bak_path):
                bak = self._try_decrypt_file(self._bak_path, self._key)
                if bak is not None:
                    self._restore_enc_from_bak()
                    self._data = bak
                    self._state = VaultState.LOADED
                    restored = True
            if not restored:
                self._state = VaultState.CORRUPT
                self._data = None
            raise VaultError("vault write did not verify; last-good backup "
                             + ("restored" if restored else "unavailable"))

        if int(verify.get("rev", -1)) != new_rev:
            # An external process clobbered vault.enc between our replace and our
            # read-back (single-instance scope, but detected not ignored).
            # Reload once to reflect on-disk truth, then surface the conflict
            # rather than blindly overwriting.
            self._data = verify
            self._state = VaultState.LOADED
            raise VaultError("vault rev read-back mismatch; external write "
                             "detected, in-memory state reloaded from disk")

    def _atomic_write(self, path: str, data: bytes) -> None:
        """Write ``data`` to ``path`` atomically: temp file in the same dir,
        fsync, then ``os.replace``. Leaves ``path`` either fully old or fully
        new, never truncated."""
        directory = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".vault.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        # Best-effort durability of the rename itself.
        try:
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    def _restore_enc_from_bak(self) -> None:
        """Copy the last-good backup over ``vault.enc`` atomically."""
        with open(self._bak_path, "rb") as f:
            data = f.read()
        self._atomic_write(self._enc_path, data)

    # ── Master-key location seam (ad-hoc now, data-protection when signed) ──

    def _is_data_protection_capable(self) -> bool:
        """Whether the running app can use the data-protection Keychain for the
        master key. Requires a signed build with the keychain-access-groups /
        application-identifier entitlement; ad-hoc builds lack it. For this
        milestone we are always ad-hoc, so this is False and the key lives in
        ``vault.key``. Milestone 6 fills in the real entitlement probe."""
        return False

    def _read_master_key(self) -> bytes | None:
        """Return the 256-bit master key, or ``None`` if it is absent /
        unreadable / malformed. Routes to the data-protection Keychain on a
        capable build, else the local key file."""
        if self._is_data_protection_capable():
            return self._read_master_key_dp()
        return self._read_master_key_file()

    def _write_master_key(self, key: bytes) -> None:
        """Persist the master key via the location seam."""
        if self._is_data_protection_capable():
            self._write_master_key_dp(key)
            return
        self._write_master_key_file(key)

    # Ad-hoc key-file backend.

    def _read_master_key_file(self) -> bytes | None:
        try:
            with open(self._key_path, "rb") as f:
                raw = f.read()
        except OSError:
            return None
        if len(raw) != _KEY_LEN:
            # Malformed key: treat as unreadable so an existing vault.enc becomes
            # KEY_MISSING rather than silently regenerating and orphaning it.
            _dbg(f"[Vault] key: unexpected length {len(raw)} (want {_KEY_LEN})")
            return None
        return raw

    def _write_master_key_file(self, key: bytes) -> None:
        self._atomic_write(self._key_path, key)

    # Data-protection Keychain backend (Milestone 6 - not on the ad-hoc path).

    def _read_master_key_dp(self) -> bytes | None:
        raise NotImplementedError(
            "data-protection Keychain master-key read lands in Milestone 6"
        )

    def _write_master_key_dp(self, key: bytes) -> None:
        raise NotImplementedError(
            "data-protection Keychain master-key write lands in Milestone 6"
        )

    def _generate_and_store_key(self) -> bytes:
        """Create a fresh random 256-bit master key and persist it via the seam.
        Called only on the first write of a fresh vault."""
        key = AESGCM.generate_key(bit_length=256)
        self._write_master_key(key)
        _dbg("[Vault] key: generated new master key")
        return key
