"""
Machine-bound encrypted credential storage (v2).

Credentials are now stored in the OS-native credential store (e.g. Secret Service
on Linux, Keychain on macOS, Credential Locker on Windows) via the `keyring` library.

The metadata (order, labels, usernames) is kept in a plain JSON config,
while the sensitive part (passwords) is stored in the keyring keyed by a UUID.
"""

from __future__ import annotations

import os
import json
import stat
import time
import uuid
import threading
from collections.abc import Callable
from datetime import datetime
import keyring
import keyring.backend
import sys
if sys.platform == "linux":
    try:
        from utils import kwallet_jeepney as _kwallet_jeepney  # noqa: F401  (registers subclass)
    except Exception:
        _kwallet_jeepney = None
else:
    _kwallet_jeepney = None

from utils.models import AccountCredential

# Total storage cap across BOTH games. The launch tab enforces a per-game
# ceiling of 16 (MAX_PER_GAME); with two games that is up to 32 accounts total.
MAX_ACCOUNTS = 32

# Per-item timeout for the one-time darwin legacy->vault migration reads/deletes.
# Generous because each un-migrated item may show a one-time macOS Keychain ACL
# prompt at this calm post-gate moment (decoupled from any game login).
_MACOS_MIGRATION_TIMEOUT = 30.0

# Always-on diagnostic log. Writes to a file independent of stdout/console
# state, so issues inside PyInstaller --noconsole builds (e.g. AppImage) can
# still be diagnosed after-the-fact.
from utils.build_flavor import config_dir as _config_dir, keyring_service, cc_token_service
_DEBUG_LOG_PATH = os.path.join(_config_dir(), "keyring-debug.log")
_DEBUG_LOG_LOCK = threading.Lock()
_DEBUG_LOG_MAX_BYTES = 256 * 1024  # rotate past 256 KiB
_DEBUG_LOG_CALLBACK = None


def set_debug_log_callback(cb):
    """Register an optional tee for credential diagnostics (e.g. in-app logger)."""
    global _DEBUG_LOG_CALLBACK
    _DEBUG_LOG_CALLBACK = cb


def _dbg(msg: str):
    """Write a diagnostic message to stdout (if available), the debug file,
    and any registered tee callback. Never raises."""
    try:
        print(msg)
    except Exception:
        pass
    try:
        with _DEBUG_LOG_LOCK:
            os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
            if os.path.exists(_DEBUG_LOG_PATH):
                try:
                    if os.path.getsize(_DEBUG_LOG_PATH) > _DEBUG_LOG_MAX_BYTES:
                        os.replace(_DEBUG_LOG_PATH, _DEBUG_LOG_PATH + ".1")
                except OSError:
                    pass
            with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S.%f}] {msg}\n")
    except Exception:
        pass
    cb = _DEBUG_LOG_CALLBACK
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


class CredentialsManager:
    """Manages TTR and Corporate Clash account credentials (up to 16 per game)
    using the system keyring."""

    def __init__(self):
        import sys
        _dbg(f"[CredentialsManager] Init. frozen={getattr(sys, 'frozen', False)} "
             f"meipass={getattr(sys, '_MEIPASS', None)} python={sys.version.split()[0]} "
             f"platform={sys.platform} session={os.getenv('XDG_SESSION_TYPE', '')} "
             f"desktop={os.getenv('XDG_CURRENT_DESKTOP', '')} "
             f"dbus={'set' if os.getenv('DBUS_SESSION_BUS_ADDRESS') else 'unset'}")
        config_dir = _config_dir()
        os.makedirs(config_dir, exist_ok=True)
        os.chmod(config_dir, 0o700)
        self._path = os.path.join(config_dir, "accounts.json")
        self._fallback_path = os.path.join(config_dir, "passwords_fallback.json")
        self._accounts: list[dict] = []
        self._fallback_passwords: dict[str, tuple[str, float]] = {}  # id -> (password, timestamp)
        self._fallback_max_age = 3600  # 1 hour max in-memory retention
        self._fallback_lock = threading.Lock()
        self._use_keyring = True
        self._probe_complete = False
        self._legacy_fallback_deleted = False
        self._deferred_v1_migration = False
        self._primary_backend_name = None
        self._change_callbacks: list[Callable[[], None]] = []  # subscribers fired on add/delete/clear_all

        # macOS credential vault (darwin only). On Linux/Windows both handles
        # stay None and the vault module is never imported, so every accessor
        # below falls straight through to the existing keyring path unchanged.
        self._macos_vault = None
        self._macos_vault_fallback = None
        self._VaultState = None
        self._VaultError = None
        # Darwin launch-unlock outcome for the UI (inert on Linux/Windows).
        # "pending" until the biometric gate resolves on the probe worker
        # thread; then one of "unlocked" | "denied" | "none" | "corrupt".
        # Guarded by a small lock because it is set off the worker thread and
        # read from the UI thread.
        self._macos_unlock_state = "pending"
        self._macos_unlock_lock = threading.Lock()
        if sys.platform == "darwin":
            self._init_macos_vault()

        self._cleanup_legacy_fallback_file()

        self._migrate_from_v1(config_dir)
        self._load()
        _dbg(f"[CredentialsManager] Loaded {len(self._accounts)} accounts from {self._path}")

    # ── Change notifications ───────────────────────────────────────────────

    def on_change(self, callback: Callable[[], None]) -> None:
        """Register a callback fired after add_account / delete_account /
        clear_all. Callbacks take no arguments. Exceptions inside callbacks
        are caught and logged, never propagated.

        Mirrors SettingsManager.on_change so KeymapTab and other consumers
        can subscribe to account-roster changes without a Qt signal.
        """
        self._change_callbacks.append(callback)

    def _emit_change(self) -> None:
        for cb in self._change_callbacks:
            try:
                cb()
            except Exception as e:
                _dbg(f"[CredentialsManager] on_change callback raised: {e}")

    # ── Persistence ────────────────────────────────────────────────────────

    def _migrate_from_v1(self, config_dir):
        old_path = os.path.join(config_dir, "credentials.enc")
        if not os.path.exists(old_path):
            return

        import sys
        if sys.platform == "win32":
            # v1 was Linux-only, so just clean up if file exists
            try:
                os.remove(old_path)
            except OSError as e:
                _dbg(f"[CredentialsManager] Failed to remove legacy v1 file: {e}")
            return

        if not self.keyring_available:
            self._deferred_v1_migration = True
            _dbg("[CredentialsManager] Keyring unavailable or probe pending; deferring v1 credential migration.")
            return

        _dbg("[CredentialsManager] Migrating credentials from v1 to keyring...")
        
        try:
            import base64
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            
            # Recreate get_machine_key logic inline for migration
            machine_id = ""
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    with open(path, "r") as f:
                        machine_id = f.read().strip()
                        break
                except FileNotFoundError:
                    continue
            if not machine_id:
                machine_id = os.uname().nodename
                try:
                    with open("/proc/sys/kernel/random/boot_id", "r") as f:
                        machine_id += f.read().strip()
                except FileNotFoundError:
                    pass

            uid = str(os.getuid())
            material = f"{machine_id}:{uid}".encode()

            # NOTE: The v1 salt is static (known weakness). This is acceptable
            # because: (a) migration runs exactly once, (b) the .enc file is
            # deleted immediately after, and (c) v2 stores passwords in the
            # OS keyring with no file-based encryption at all.
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"toontown-multitool-v1-cred-salt",
                iterations=480_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(material))
            
            fernet = Fernet(key)
            with open(old_path, "rb") as f:
                encrypted = f.read()
            decrypted = fernet.decrypt(encrypted)
            old_accounts = json.loads(decrypted.decode())
            
            for acc in old_accounts:
                account_id = str(uuid.uuid4())
                password = acc.get("password", "")
                
                if password:
                    self._set_password(account_id, password)
                
                self._accounts.append({
                    "id": account_id,
                    "label": acc.get("label", ""),
                    "username": acc.get("username", "")
                })
            
            self._save()

            backup_path = old_path + ".migrated"
            try:
                import shutil
                shutil.move(old_path, backup_path)
                _dbg("[CredentialsManager] Migration successful. Old file archived as .migrated")
            except Exception as e:
                _dbg(f"[CredentialsManager] Warning: could not archive old credentials: {e}")

            self._deferred_v1_migration = False
            
        except Exception as e:
            _dbg(f"[CredentialsManager] Failed to migrate v1 credentials: {type(e).__name__}")

    def _load(self):
        if not os.path.exists(self._path):
            self._accounts = []
            return
        try:
            with open(self._path, "r") as f:
                self._accounts = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _dbg(f"[CredentialsManager] Failed to load accounts: {e}")
            self._accounts = []

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._accounts, f, indent=4)
            # Restrict file permissions
            os.chmod(self._path, 0o600)
        except Exception as e:
            _dbg(f"[CredentialsManager] Failed to save accounts: {e}")

    def _cleanup_legacy_fallback_file(self):
        if os.path.exists(self._fallback_path):
            try:
                if stat.S_ISREG(os.lstat(self._fallback_path).st_mode):
                    size = os.path.getsize(self._fallback_path)
                    with open(self._fallback_path, "wb") as f:
                        f.write(b"\x00" * size)
                os.remove(self._fallback_path)
                self._legacy_fallback_deleted = True
            except Exception as e:
                _dbg(f"[CredentialsManager] Failed to delete legacy fallback password store: {type(e).__name__}")
                self._legacy_fallback_deleted = False
        else:
            self._legacy_fallback_deleted = False

    def _init_macos_vault(self) -> None:
        """Wire up the macOS credential vault (darwin only).

        Normal darwin: the vault is the primary secret store. Kill switch
        (``TTMT_MACOS_VAULT=0``): no primary vault, but a read-only fallback so
        secrets that already moved into the vault are still reachable via the
        legacy path. Any import/construction failure degrades to the legacy
        keyring path rather than breaking construction.
        """
        try:
            from utils.macos_credential_vault import MacOSCredentialVault, VaultState, VaultError
        except Exception as e:
            _dbg(f"[CredentialsManager] macOS vault unavailable ({type(e).__name__}); using legacy keyring path.")
            return
        self._VaultState = VaultState
        self._VaultError = VaultError
        try:
            if os.environ.get("TTMT_MACOS_VAULT") == "0":
                self._macos_vault = None
                self._macos_vault_fallback = MacOSCredentialVault()
                _dbg("[CredentialsManager] macOS vault kill switch (TTMT_MACOS_VAULT=0): legacy writes, vault read-fallback.")
            else:
                self._macos_vault = MacOSCredentialVault()
                self._macos_vault_fallback = None
                _dbg("[CredentialsManager] macOS credential vault active (primary store).")
        except Exception as e:
            self._macos_vault = None
            self._macos_vault_fallback = None
            _dbg(f"[CredentialsManager] macOS vault construction failed ({type(e).__name__}); using legacy keyring path.")

    def run_probe(self, timeout: float = 45.0) -> bool:
        """
        Probe the keyring from a background thread.

        Two-step: read the probe key, then write it if it doesn't exist yet.
        Either step forces the wallet unlock dialog (if the wallet is locked),
        giving the user up to `timeout` seconds to respond. Once the wallet is
        open it stays open for the session, so subsequent _get_password calls
        (which use a short 1.5s timeout) succeed without re-prompting.
        """
        if self._macos_vault is not None:
            # Darwin: the launch-time "probe" is the single biometric gate plus a
            # vault load and the one-time legacy migration. No keyring probe. The
            # UI re-triggers a gate simply by re-running this on the worker.
            return self._macos_unlock()
        _dbg(f"[Credentials] Probe start: selected={type(keyring.get_keyring()).__module__}."
             f"{type(keyring.get_keyring()).__name__} timeout={timeout}")
        # Step 1: read the probe key. Forces wallet unlock if key exists.
        ok, value = self._try_keyring_call(
            keyring.get_password, keyring_service(), "__ttmt_probe__", timeout=timeout
        )
        _dbg(f"[Credentials] Probe step1 (get): ok={ok} value={'present' if value else 'none/empty'}")
        if not ok:
            self._use_keyring = False
            self._probe_complete = True
            _dbg("[CredentialsManager] Keyring unavailable/unresponsive; passwords will not be saved between sessions.")
            return False

        if value is None:
            # Probe key doesn't exist yet — write it. Writing to a locked wallet
            # forces the unlock dialog, so this serves the same purpose as a read
            # on an existing key. After this, the wallet is open for the session.
            ok, _ = self._try_keyring_call(
                keyring.set_password, keyring_service(), "__ttmt_probe__", "1", timeout=timeout
            )
            _dbg(f"[Credentials] Probe step2 (set): ok={ok}")
            if not ok:
                # Write failed — user likely dismissed the unlock dialog.
                self._use_keyring = False
                self._probe_complete = True
                _dbg("[CredentialsManager] Keyring write failed (wallet dismissed?); passwords will not be saved between sessions.")
                return False

        self._wake_kwallet_if_relevant(timeout)
        self._use_keyring = True
        self._probe_complete = True
        self._primary_backend_name = self._detect_primary_backend_name()
        _dbg(f"[Credentials] Probe complete: primary_backend={self._primary_backend_name}")
        if self._deferred_v1_migration:
            self.run_deferred_v1_migration()
        return True

    def run_deferred_v1_migration(self):
        if self._deferred_v1_migration and self.keyring_available:
            self._migrate_from_v1(os.path.dirname(self._path))

    # ── macOS launch-unlock (darwin only) ───────────────────────────────────

    def _set_macos_unlock_state(self, state: str) -> None:
        with self._macos_unlock_lock:
            self._macos_unlock_state = state

    @property
    def macos_unlock_state(self) -> str:
        """Read-only view of the darwin launch-unlock outcome for the UI:
        "pending" | "unlocked" | "denied" | "none" | "corrupt". Always
        "pending" (and unused) on Linux/Windows."""
        with self._macos_unlock_lock:
            return self._macos_unlock_state

    def _emit_vault_stamp(self, unlock: str, migrated: int) -> None:
        """Startup stamp (running-code proof). Emitted via ``_dbg`` (which always
        prints), so live-validation can grep it. The format is stable - do not
        reflow: ``[Vault] mode=<...> accounts=<N> unlock=<...> migrated=<M>``."""
        _dbg(f"[Vault] mode=adhoc-keyfile accounts={len(self._accounts)} "
             f"unlock={unlock} migrated={migrated}")

    def _macos_unlock(self) -> bool:
        """Darwin launch-unlock orchestrator (runs on the KeyringProbeWorker
        BACKGROUND thread, so a blocking system auth dialog is fine here).

        Runs the SINGLE biometric gate (Touch ID / Apple Watch / Mac password),
        loads the vault on success, runs the one-time legacy->vault migration,
        emits the startup stamp, and records the outcome in
        ``self._macos_unlock_state``. Never prompts when nothing is saved and
        never raises out of the probe worker.
        """
        migrated = 0

        # Hard requirement: never gate when nothing may be saved.
        if not self.macos_secret_may_exist():
            self._macos_vault.load()
            self._set_macos_unlock_state("none")
            self._emit_vault_stamp("none", migrated)
            return True

        # A secret may exist -> exactly one auth prompt.
        try:
            from services import macos_biometric_gate as gate
            result = gate.authenticate("Unlock your ToonTown MultiTool accounts")
        except Exception as e:
            # Import/call failure is treated like a failed gate: never crash the
            # probe worker, leave the vault NOT_LOADED, show the locked UI.
            _dbg(f"[Vault] biometric gate raised ({type(e).__name__}: {e}); treating as denied.")
            self._set_macos_unlock_state("denied")
            self._emit_vault_stamp("denied", migrated)
            return False

        BR = gate.BiometricResult
        if result == BR.SUCCESS:
            state = self._macos_vault.load()
            if state == self._VaultState.LOADED:
                migrated = self._macos_migrate_legacy_to_vault()
                # A failed write-verify during migration can drive the vault
                # CORRUPT; reflect that rather than reporting a false unlock.
                if self._macos_vault.state == self._VaultState.LOADED:
                    self._set_macos_unlock_state("unlocked")
                    self._emit_vault_stamp("gate", migrated)
                    return True
                self._set_macos_unlock_state("corrupt")
                self._emit_vault_stamp("corrupt", migrated)
                return False
            # Gate passed but the vault is CORRUPT / KEY_MISSING (no data loss:
            # the raw file is preserved). Surface the recovery state.
            self._set_macos_unlock_state("corrupt")
            self._emit_vault_stamp("corrupt", migrated)
            return False

        if result == BR.UNAVAILABLE:
            # Deliberate fail-open: no auth method configured at all, so there is
            # no local security boundary to honor. Load without a gate + migrate.
            self._macos_vault.load()
            if self._macos_vault.state == self._VaultState.LOADED:
                migrated = self._macos_migrate_legacy_to_vault()
            self._set_macos_unlock_state("none")
            self._emit_vault_stamp("none", migrated)
            return True

        # CANCELLED or FAILED: do NOT load; leave the vault NOT_LOADED so the UI
        # shows the "Unlock accounts" affordance and re-running re-gates.
        self._set_macos_unlock_state("denied")
        self._emit_vault_stamp("denied", migrated)
        return False

    def _macos_migrate_legacy_to_vault(self) -> int:
        """One-time controlled migration of legacy per-account Keychain items
        into the vault. Called ONLY from :meth:`_macos_unlock` AFTER a successful
        vault load - never inline on a toon launch. Returns the number of
        accounts migrated (touched) this run for the startup stamp.

        Write-verify-THEN-delete: the vault persists + reads back internally, and
        the legacy item is deleted only after the vault write did not raise. A
        :class:`VaultError` (CORRUPT / KEY_MISSING) stops the whole migration
        without deleting anything; one bad account never aborts the rest.
        """
        # The gate has passed; allow the timeout-guarded keyring wrapper to make
        # the migration reads/deletes (its probe guard otherwise blocks deletes).
        self._probe_complete = True
        migrated = 0
        for a in list(self._accounts):
            account_id = a.get("id")
            if not account_id:
                continue
            game = a.get("game", "ttr")
            try:
                if self._macos_migrate_one_account(account_id, game):
                    migrated += 1
            except Exception as e:
                # A VaultError (CORRUPT / KEY_MISSING) means a write refused, so
                # nothing was deleted for this account - STOP the whole migration
                # rather than risk deleting a legacy item the vault cannot store.
                if self._VaultError is not None and isinstance(e, self._VaultError):
                    _dbg(f"[Vault] migration halted at {account_id[:8]} "
                         f"({type(e).__name__}: {e}); nothing deleted.")
                    break
                # Any other per-account failure is logged and skipped so one bad
                # account never aborts the rest.
                _dbg(f"[Vault] migration skipped {account_id[:8]} "
                     f"({type(e).__name__}: {e}).")
                continue
        return migrated

    def _macos_migrate_one_account(self, account_id: str, game: str) -> bool:
        """Migrate one account's legacy secrets into the vault. Returns True if
        any namespace was touched this run (so it is counted once even when both
        a password and a CC token migrate). Raises the vault's ``VaultError`` if a
        vault write refuses (CORRUPT / KEY_MISSING) - the caller stops migration.
        """
        did_work = False

        # Passwords namespace (all games). Skip if already migrated.
        if not self._macos_vault.has_password(account_id):
            ok, value = self._try_keyring_call(
                keyring.get_password, keyring_service(), account_id,
                timeout=_MACOS_MIGRATION_TIMEOUT,
            )
            if not ok:
                # Keyring read failed (timeout / backend error): leave the item
                # un-migrated so a later run retries. Never mark it absent (that
                # would strand a real legacy secret).
                _dbg(f"[Vault] migration: legacy password read failed for "
                     f"{account_id[:8]}; leaving un-migrated.")
            else:
                if value is not None:
                    # Write-verify FIRST (raises on a bad verify), then delete.
                    self._macos_vault.set_password(account_id, value)
                    self._try_keyring_call(
                        keyring.delete_password, keyring_service(), account_id,
                        timeout=_MACOS_MIGRATION_TIMEOUT,
                    )
                    _dbg(f"[Vault] migrated password for {account_id[:8]} "
                         "(legacy item removed).")
                else:
                    # No legacy secret: record a known-absent marker so the
                    # legacy item is never probed again.
                    self._macos_vault.set_password(account_id, None)
                did_work = True

        # CC launcher-token namespace (CC accounts only).
        if game == "cc" and not self._macos_vault.has_token(account_id):
            ok, value = self._try_keyring_call(
                keyring.get_password, cc_token_service(), account_id,
                timeout=_MACOS_MIGRATION_TIMEOUT,
            )
            if not ok:
                _dbg(f"[Vault] migration: legacy CC token read failed for "
                     f"{account_id[:8]}; leaving un-migrated.")
            else:
                if value is not None:
                    self._macos_vault.set_token(account_id, value)
                    self._try_keyring_call(
                        keyring.delete_password, cc_token_service(), account_id,
                        timeout=_MACOS_MIGRATION_TIMEOUT,
                    )
                    _dbg(f"[Vault] migrated CC token for {account_id[:8]} "
                         "(legacy item removed).")
                else:
                    self._macos_vault.set_token(account_id, None)
                did_work = True

        return did_work

    def _try_keyring_call(self, func, *args, timeout=1.5):
        if not self._use_keyring:
            return False, None
        # During the probe window, only get_password and set_password are allowed
        # through. get_password is used in probe step 1; set_password is used in
        # probe step 2 (writing the probe key to force wallet unlock when the key
        # doesn't exist yet). All other calls (delete_password etc.) are blocked
        # until the probe completes.
        #
        # NOTE: non-probe get_password calls are also allowed through here, but
        # with only a 1.5s timeout. This is safe because the UI disables launch
        # buttons while keyring_probe_pending is True, so no _get_password calls
        # can arrive during the probe window. If that UI contract ever changes,
        # tighten this guard to distinguish probe calls from non-probe calls.
        if not self._probe_complete and func not in (keyring.get_password, keyring.set_password):
            return False, None
        result = {"value": None, "error": None}
        done = threading.Event()

        def _runner():
            try:
                result["value"] = func(*args)
            except Exception as e:
                result["error"] = e
            finally:
                done.set()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        try:
            if not done.wait(timeout):
                self._use_keyring = False
                self._probe_complete = True
                _dbg(f"[CredentialsManager] Keyring call timed out ({getattr(func, '__name__', 'func')}, timeout={timeout}s); "
                     "passwords will not be saved between sessions.")
                return False, None
            if result["error"] is not None:
                # Some backends (notably kwallet.DBusKeyring) raise an exception
                # when get_password is called for a non-existent key, instead of
                # returning None. This is a backend quirk, not a keyring failure.
                # Treat it as a successful call returning None so the probe and
                # normal reads don't incorrectly mark the keyring as unavailable.
                if func is keyring.get_password:
                    err_msg = str(result["error"]).lower()
                    if any(p in err_msg for p in ("not found", "no item", "does not exist", "no such")):
                        return True, None
                # WinVaultKeyring (and most other backends) raise
                # PasswordDeleteError when delete_password is called for a
                # non-existent key. That's the no-op case, not a backend
                # failure: don't tear down the keyring for the rest of the
                # session. The CC-token clear path hits this on every account
                # that never had a launcher token saved, which is what
                # surfaced "Credential Storage Unavailable" on Windows.
                if func is keyring.delete_password:
                    from keyring.errors import PasswordDeleteError
                    if isinstance(result["error"], PasswordDeleteError):
                        return True, None
                if func is keyring.set_password:
                    from keyring.errors import PasswordSetError
                    if isinstance(result["error"], PasswordSetError):
                        # Transient KWallet/Secret Service write failure — log and report
                        # failure, but keep the keyring backend usable for retry.
                        _dbg(f"keyring write failed (transient): {result['error']!r}")
                        return (False, None)
                raise result["error"]
            return True, result["value"]
        except Exception as e:
            _dbg(f"[CredentialsManager] Keyring {getattr(func, '__name__', 'func')} raised "
                 f"{type(e).__name__}: {e}")
            self._use_keyring = False
            self._probe_complete = True
            _dbg(
                "[CredentialsManager] Keyring call failed "
                f"({type(e).__name__}); passwords will not be saved between sessions."
            )
            return False, None

    def _available_explicit_backends(self) -> list:
        seen = set()
        result = []
        manual_candidates = []
        def _priority(backend):
            try:
                return getattr(backend, "priority")
            except Exception:
                return -1
        try:
            backends = list(keyring.backend.get_all_keyring())
        except Exception:
            backends = []
        try:
            from keyring.backends import SecretService
            manual_candidates.append(SecretService.Keyring())
        except Exception:
            pass
        try:
            from keyring.backends import libsecret
            manual_candidates.append(libsecret.Keyring())
        except Exception:
            pass
        try:
            from keyring.backends import kwallet
            manual_candidates.append(kwallet.DBusKeyring())
        except Exception:
            pass
        try:
            if _kwallet_jeepney is not None:
                manual_candidates.append(_kwallet_jeepney.JeepneyKWalletBackend())
        except Exception:
            pass
        backends.extend(manual_candidates)
        backends.sort(key=_priority, reverse=True)
        for backend in backends:
            backend_type = type(backend)
            name = f"{backend_type.__module__}.{backend_type.__name__}"
            mod = backend_type.__module__.lower()
            if "chainer" in mod or "fail" in mod:
                continue
            if name in seen:
                continue
            seen.add(name)
            result.append(backend)
        return result

    def _call_backend_method(self, backend, method_name: str, *args, timeout=1.5):
        result = {"value": None, "error": None}
        done = threading.Event()

        def _runner():
            try:
                result["value"] = getattr(backend, method_name)(*args)
            except Exception as e:
                result["error"] = e
            finally:
                done.set()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        if not done.wait(timeout):
            return False, None
        if result["error"] is not None:
            if method_name == "get_password":
                err_msg = str(result["error"]).lower()
                if any(p in err_msg for p in ("not found", "no item", "does not exist", "no such")):
                    return True, None
            return False, result["error"]
        return True, result["value"]

    def _backend_name(self, backend) -> str:
        backend_type = type(backend)
        return f"{backend_type.__module__}.{backend_type.__name__}"

    def _detect_primary_backend_name(self) -> str | None:
        for backend in self._available_explicit_backends():
            ok, value = self._call_backend_method(
                backend, "get_password", keyring_service(), "__ttmt_probe__", timeout=1.5
            )
            if ok and value:
                return self._backend_name(backend)
        return None

    def _wake_kwallet_if_relevant(self, timeout: float):
        if os.getenv("XDG_SESSION_TYPE", "").lower() != "wayland":
            return
        if "KDE" not in os.getenv("XDG_CURRENT_DESKTOP", "").split(":"):
            return
        for backend in self._available_explicit_backends():
            backend_name = self._backend_name(backend)
            if backend_name not in (
                "keyring.backends.kwallet.DBusKeyring",
                "utils.kwallet_jeepney.JeepneyKWalletBackend",
            ):
                continue
            ok, value = self._call_backend_method(
                backend, "get_password", keyring_service(), "__ttmt_probe__", timeout=timeout
            )
            if ok:
                state = "value-present" if value else "value-empty-or-none"
                _dbg(f"[Credentials] Direct KWallet probe succeeded [{state}].")
            else:
                _dbg("[Credentials] Direct KWallet probe failed or timed out.")
            return

    def _migrate_password_to_primary_backend(self, account_id: str, password: str, source_backend_name: str):
        if not password:
            return
        target_name = self._primary_backend_name
        if not target_name or target_name == source_backend_name:
            return
        for backend in self._available_explicit_backends():
            backend_name = self._backend_name(backend)
            if backend_name != target_name:
                continue
            ok, _ = self._call_backend_method(
                backend, "set_password", keyring_service(), account_id, password, timeout=2.0
            )
            if ok:
                _dbg(
                    f"[Credentials] Recovered password from {source_backend_name} "
                    f"and migrated it to {target_name}."
                )
            return

    def _recover_password_from_compatible_backends(self, account_id: str) -> str:
        cumulative_timeout = 5.0
        start = time.monotonic()
        for backend in self._available_explicit_backends():
            if time.monotonic() - start > cumulative_timeout:
                _dbg(f"[Credentials] Backend recovery timed out after {cumulative_timeout}s.")
                break
            backend_name = self._backend_name(backend)
            remaining = max(0.5, cumulative_timeout - (time.monotonic() - start))
            ok, value = self._call_backend_method(
                backend, "get_password", keyring_service(), account_id, timeout=min(1.5, remaining)
            )
            if ok and value:
                self._migrate_password_to_primary_backend(account_id, value, backend_name)
                _dbg(f"[Credentials] Recovered password via {backend_name}.")
                return value
        return ""

    def get_launcher_token(self, account_id: str) -> str:
        """Return CC launcher token for an account, or '' if none stored.

        Best-effort: keyring failures (timeout, missing backend, etc.)
        degrade to ''. Never raises. Matches the threading and
        timeout discipline of ``_get_password``.
        """
        if not account_id:
            return ""
        if self._macos_vault is not None:
            try:
                return self._macos_vault.get_token(account_id)
            except Exception as e:
                _dbg(f"[CredentialsManager] get_launcher_token({account_id[:8]}) vault read failed: {type(e).__name__}")
                return ""
        value = self._get_launcher_token_legacy(account_id)
        if not value and self._macos_vault_fallback is not None:
            try:
                recovered = self._macos_vault_fallback.get_token(account_id)
                if recovered:
                    return recovered
            except Exception as e:
                _dbg(f"[CredentialsManager] get_launcher_token({account_id[:8]}) vault fallback read failed: {type(e).__name__}")
        return value

    def _get_launcher_token_legacy(self, account_id: str) -> str:
        if not account_id:
            return ""
        try:
            ok, value = self._try_keyring_call(
                keyring.get_password, cc_token_service(), account_id, timeout=1.5
            )
            if ok and value:
                return value
            return ""
        except Exception as e:
            _dbg(f"[CredentialsManager] get_launcher_token({account_id[:8]}) failed: {type(e).__name__}: {e}")
            return ""

    def set_launcher_token(self, account_id: str, token: str) -> None:
        """Persist a CC launcher token. Overwrites any existing entry.

        Best-effort: keyring failures are logged via ``_dbg`` but don't
        raise. Empty ``token`` is treated as a clear request. Uses the
        channel-aware ``cc_token_service()`` and routes the keyring call
        through ``_try_keyring_call`` for timeout safety.
        """
        if not account_id:
            return
        if not token:
            self.clear_launcher_token(account_id)
            return
        if self._macos_vault is not None:
            try:
                self._macos_vault.set_token(account_id, token)
            except Exception as e:
                _dbg(f"[CredentialsManager] set_launcher_token({account_id[:8]}) vault write failed: {type(e).__name__}")
            return
        try:
            ok, _ = self._try_keyring_call(
                keyring.set_password, cc_token_service(), account_id, token, timeout=1.5
            )
            if not ok:
                _dbg(f"[CredentialsManager] set_launcher_token({account_id[:8]}) failed: keyring call did not complete")
        except Exception as e:
            _dbg(f"[CredentialsManager] set_launcher_token({account_id[:8]}) failed: {type(e).__name__}: {e}")

    def clear_launcher_token(self, account_id: str) -> None:
        """Remove the launcher-token entry for an account. No-op if absent.

        Called when the token has been revoked server-side, or when the
        user updates a CC account's username/password (which invalidates
        any prior registration). Uses the channel-aware
        ``cc_token_service()`` and routes the keyring call through
        ``_try_keyring_call`` for timeout safety.
        """
        if not account_id:
            return
        if self._macos_vault is not None:
            try:
                self._macos_vault.clear_token(account_id)
            except Exception as e:
                _dbg(f"[CredentialsManager] clear_launcher_token({account_id[:8]}) vault clear failed: {type(e).__name__}")
            return
        try:
            self._try_keyring_call(
                keyring.delete_password, cc_token_service(), account_id, timeout=1.5
            )
        except Exception:
            # Most keyring backends raise PasswordDeleteError when the
            # entry doesn't exist. That's the no-op case; ignore.
            # ``_try_keyring_call`` already swallows backend errors into
            # ``ok=False``; this except handles any escape from the wrapper.
            pass

    def _get_password(self, account_id: str) -> str:
        # macOS routes reads to the credential vault. On Linux/Windows both vault
        # handles are None, so this dispatches straight to the legacy body below
        # and the result is byte-identical to before.
        if not account_id:
            _dbg("[Credentials] _get_password called with empty account_id")
            return ""
        if self._macos_vault is not None:
            try:
                return self._macos_vault.get_password(account_id)
            except Exception as e:
                _dbg(f"[Credentials] _get_password vault read failed: {type(e).__name__}")
                return ""
        value = self._get_password_legacy(account_id)
        if not value and self._macos_vault_fallback is not None:
            # Kill switch: legacy read was empty; recover an already-migrated
            # secret from the vault so users are not stranded.
            try:
                recovered = self._macos_vault_fallback.get_password(account_id)
                if recovered:
                    _dbg("[Credentials] _get_password: recovered from vault fallback (kill switch)")
                    return recovered
            except Exception as e:
                _dbg(f"[Credentials] _get_password vault fallback read failed: {type(e).__name__}")
        return value

    def _get_password_legacy(self, account_id: str) -> str:
        if not account_id:
            _dbg("[Credentials] _get_password called with empty account_id")
            return ""
        short_id = account_id[:8]
        ok, value = self._try_keyring_call(keyring.get_password, keyring_service(), account_id, timeout=1.5)
        _dbg(f"[Credentials] _get_password({short_id}): ok={ok} value={'present' if value else 'empty'}")
        if ok:
            if value:
                return value
            if self._probe_complete:
                recovered = self._recover_password_from_compatible_backends(account_id)
                _dbg(f"[Credentials] _get_password({short_id}): recovered={'present' if recovered else 'empty'}")
                if recovered:
                    return recovered
            return ""
        if self._probe_complete:
            recovered = self._recover_password_from_compatible_backends(account_id)
            _dbg(f"[Credentials] _get_password({short_id}) fallback-path: recovered={'present' if recovered else 'empty'}")
            if recovered:
                return recovered
        with self._fallback_lock:
            entry = self._fallback_passwords.get(account_id)
            if entry:
                password, timestamp = entry
                if time.monotonic() - timestamp > self._fallback_max_age:
                    del self._fallback_passwords[account_id]
                    _dbg(f"[Credentials] In-memory password expired.")
                    return ""
                _dbg(f"[Credentials] _get_password({short_id}): using in-memory fallback")
                return password
        _dbg(f"[Credentials] _get_password({short_id}): returning empty")
        return ""

    def _set_password(self, account_id: str, password: str) -> bool:
        if not account_id:
            return False
        if self._macos_vault is not None:
            try:
                self._macos_vault.set_password(account_id, password)
                return True
            except Exception as e:
                _dbg(f"[Credentials] _set_password vault write failed: {type(e).__name__}")
                return False
        if not self._use_keyring:
            with self._fallback_lock:
                self._fallback_passwords[account_id] = (password or "", time.monotonic())
            return True
        ok, _ = self._try_keyring_call(keyring.set_password, keyring_service(), account_id, password, timeout=1.5)
        if ok:
            with self._fallback_lock:
                self._fallback_passwords.pop(account_id, None)
            return True
        with self._fallback_lock:
            self._fallback_passwords[account_id] = (password or "", time.monotonic())
        _dbg(f"[Credentials] WARNING: Password stored in volatile memory (keyring unavailable). "
              f"It will be cleared after {self._fallback_max_age // 60} minutes or on restart.")
        return True

    def _delete_password(self, account_id: str):
        if not account_id:
            return
        if self._macos_vault is not None:
            try:
                self._macos_vault.delete_password(account_id)
            except Exception as e:
                _dbg(f"[Credentials] _delete_password vault delete failed: {type(e).__name__}")
            return
        self._try_keyring_call(keyring.delete_password, keyring_service(), account_id, timeout=1.5)
        with self._fallback_lock:
            self._fallback_passwords.pop(account_id, None)

    @property
    def keyring_available(self) -> bool:
        if self._macos_vault is not None:
            return self._macos_vault.state == self._VaultState.LOADED
        return self._probe_complete and self._use_keyring

    @property
    def keyring_probe_pending(self) -> bool:
        if self._macos_vault is not None:
            return self._macos_vault.state == self._VaultState.NOT_LOADED
        return not self._probe_complete

    def macos_secret_may_exist(self) -> bool:
        """True if a credential MIGHT be stored: any account exists, or (on
        darwin) a ``vault.enc`` / ``vault.key`` file is present in
        ``config_dir()``. Pure and read-only - used by the darwin unlock-gate
        decision so the biometric gate never fires when nothing is saved."""
        if self._accounts:
            return True
        if sys.platform == "darwin":
            cfg = _config_dir()
            for name in ("vault.enc", "vault.key"):
                if os.path.exists(os.path.join(cfg, name)):
                    return True
        return False

    def get_backend_diagnostics(self) -> dict:
        backend = keyring.get_keyring()
        backend_type = type(backend)
        info = {
            "selected_backend": f"{backend_type.__module__}.{backend_type.__name__}",
            "selected_priority": getattr(backend, "priority", "unknown"),
            "primary_backend": self._primary_backend_name or "unknown",
            "probe_complete": self._probe_complete,
            "keyring_available": self.keyring_available,
            "session_type": os.getenv("XDG_SESSION_TYPE", ""),
            "current_desktop": os.getenv("XDG_CURRENT_DESKTOP", ""),
        }

        available = []
        try:
            for candidate in keyring.backend.get_all_keyring():
                candidate_type = type(candidate)
                try:
                    priority = getattr(candidate, "priority")
                except Exception as e:
                    priority = f"error:{e}"
                available.append({
                    "backend": f"{candidate_type.__module__}.{candidate_type.__name__}",
                    "priority": priority,
                })
        except Exception as e:
            available.append({"backend": "error", "priority": str(e)})
        info["available_backends"] = available

        child_backends = []
        if hasattr(backend, "backends"):
            try:
                for child in backend.backends:
                    child_type = type(child)
                    try:
                        priority = getattr(child, "priority")
                    except Exception as e:
                        priority = f"error:{e}"
                    # Use the timed wrapper so a hung child backend (e.g. a
                    # locked-but-no-prompt SecretService collection on a fresh
                    # GNOME session) cannot block the caller. Without this the
                    # diagnostic dump can hang the main thread before app.exec().
                    ok, value_or_err = self._call_backend_method(
                        child, "get_password", keyring_service(), "__ttmt_probe__", timeout=1.5
                    )
                    if ok:
                        probe_status = "ok"
                        probe_detail = "value-present" if value_or_err else "value-empty-or-none"
                    elif value_or_err is None:
                        probe_status = "timeout"
                        probe_detail = "no response within 1.5s"
                    else:
                        probe_status = "error"
                        probe_detail = f"{type(value_or_err).__name__}: {value_or_err}"
                    child_backends.append({
                        "backend": f"{child_type.__module__}.{child_type.__name__}",
                        "priority": priority,
                        "probe_status": probe_status,
                        "probe_detail": probe_detail,
                    })
            except Exception as e:
                child_backends.append({
                    "backend": "error",
                    "priority": "unknown",
                    "probe_status": "error",
                    "probe_detail": str(e),
                })
        info["child_backends"] = child_backends
        return info

    def format_backend_diagnostics(self) -> list[str]:
        info = self.get_backend_diagnostics()
        lines = [
            f"[Credentials] Selected keyring backend: {info['selected_backend']} (priority={info['selected_priority']})",
            f"[Credentials] Primary storage backend: {info['primary_backend']}",
            f"[Credentials] Session: desktop={info['current_desktop'] or 'unknown'}, session={info['session_type'] or 'unknown'}",
            f"[Credentials] Probe state: complete={info['probe_complete']}, available={info['keyring_available']}",
        ]
        available_parts = [
            f"{item['backend']} ({item['priority']})"
            for item in info["available_backends"]
        ]
        lines.append(f"[Credentials] Available backends: {', '.join(available_parts)}")
        if info["child_backends"]:
            for item in info["child_backends"]:
                lines.append(
                    "[Credentials] Chainer child: "
                    f"{item['backend']} (priority={item['priority']}), "
                    f"probe={item['probe_status']} [{item['probe_detail']}]"
                )
        return lines

    # ── Read API ───────────────────────────────────────────────────────────

    def get_accounts(self, game: str | None = None) -> list[AccountCredential]:
        """Return list of accounts as AccountCredential objects.

        If ``game`` is provided (e.g. "ttr" or "cc"), only accounts tagged
        with that game are returned.  Pass ``None`` to get all accounts.
        """
        result = []
        for a in self._accounts:
            if game is not None and a.get("game", "ttr") != game:
                continue
            account_id = a.get("id")
            if not account_id:
                _dbg(f"[CredentialsManager] Warning: skipping account with missing ID: {a.get('label', '?')}")
                continue
            password = self._get_password(account_id)

            acct = AccountCredential.from_dict(a, password)
            if acct.game == "cc":
                acct.launcher_token = self.get_launcher_token(acct.id)
            result.append(acct)
        return result

    def get_accounts_metadata(self, game: str | None = None) -> list[AccountCredential]:
        """Return account metadata without fetching passwords."""
        result = []
        for a in self._accounts:
            if game is not None and a.get("game", "ttr") != game:
                continue
            acct = AccountCredential.from_dict(a, password="")
            if acct.game == "cc":
                acct.launcher_token = self.get_launcher_token(acct.id)
            result.append(acct)
        return result

    def get_accounts_basic(self, game: str | None = None) -> list[tuple[str, str, str]]:
        """Return ``[(id, game, label)]`` for all accounts (optionally filtered by
        ``game``), sourced purely from in-memory account metadata. Performs NO
        keyring access - safe on hot GUI paths (emblem wheel open) and when the
        keyring is locked. ``label`` falls back to ``username`` then ``""``."""
        out: list[tuple[str, str, str]] = []
        for a in self._accounts:
            g = a.get("game", "ttr")
            if game is not None and g != game:
                continue
            aid = a.get("id")
            if not aid:
                continue
            out.append((aid, g, a.get("label") or a.get("username") or ""))
        return out

    def get_account(self, index: int) -> AccountCredential | None:
        if 0 <= index < len(self._accounts):
            a = self._accounts[index]
            account_id = a.get("id")
            password = self._get_password(account_id) if account_id else ""
            acct = AccountCredential.from_dict(a, password)
            if acct is not None and acct.game == "cc":
                acct.launcher_token = self.get_launcher_token(acct.id)
            return acct
        return None

    def get_account_metadata(self, index: int) -> AccountCredential | None:
        """Return account metadata without fetching the password."""
        if 0 <= index < len(self._accounts):
            acct = AccountCredential.from_dict(self._accounts[index], password="")
            if acct is not None and acct.game == "cc":
                acct.launcher_token = self.get_launcher_token(acct.id)
            return acct
        return None

    def count(self) -> int:
        return len(self._accounts)

    # ── Write API ──────────────────────────────────────────────────────────

    def add_account(self, label: str = "", username: str = "", password: str = "", game: str = "ttr") -> bool:
        """Add a new account. Returns False if at capacity."""
        if len(self._accounts) >= MAX_ACCOUNTS:
            return False

        account_id = str(uuid.uuid4())

        if not self._set_password(account_id, password):
            return False

        if not self._use_keyring:
            _dbg(f"WARNING: account {account_id} added but password held in-memory only (keyring unavailable)")

        self._accounts.append({
            "id": account_id,
            "label": label,
            "username": username,
            "game": game,
        })
        self._save()
        self._emit_change()
        return True

    def update_account(self, index: int, label: str = None, username: str = None, password: str = None):
        """Update specific fields of an account.

        password=None: do not touch the stored password.
        password="": clear the stored password (destructive).
                     Used by _persist_launcher_token in launch_tab.py to
                     discard the one-time registration password after the
                     launcher token has been obtained.
        password=<str>: overwrite the stored password with the given value.
        """
        if 0 <= index < len(self._accounts):
            a = self._accounts[index]
            game = a.get("game", "ttr")

            # Detect CC-credential mutations that invalidate any stored token.
            # An empty password ("") is treated as "no change for token
            # purposes" — the Task 11 _persist_launcher_token flow uses
            # update_account(idx, password="") to discard a one-time password
            # without touching the newly-stored launcher token.
            cc_creds_changed = (
                game == "cc"
                and ((username is not None and username != a.get("username"))
                     or (password is not None and password != ""))
            )

            if label is not None:
                a["label"] = label
            if username is not None:
                a["username"] = username
            if password is not None:
                account_id = a.get("id")
                if account_id:
                    self._set_password(account_id, password)

            self._save()

            if cc_creds_changed:
                account_id = a.get("id")
                if account_id:
                    self.clear_launcher_token(account_id)

    def delete_account(self, index: int) -> tuple[str, str | None] | None:
        """Delete the account at ``index``.

        Returns ``(account_id, token)`` where ``token`` is the CC launcher
        token previously stored for the account (or ``None`` for TTR
        accounts and CC accounts without a stored token). The caller is
        responsible for firing ``/revoke_self`` against the CC API on a
        best-effort basis.

        Returns ``None`` only when ``index`` is out of range.
        """
        if not (0 <= index < len(self._accounts)):
            return None
        a = self._accounts[index]
        account_id = a.get("id")
        game = a.get("game", "ttr")
        token: str | None = None
        if game == "cc" and account_id:
            stored = self.get_launcher_token(account_id)
            token = stored or None
            if stored:
                self.clear_launcher_token(account_id)
        # Preserve existing cleanup: pop from list, drop keyring password, save.
        self._accounts.pop(index)
        if account_id:
            self._delete_password(account_id)
        self._save()
        self._emit_change()
        return (account_id or "", token)

    def reorder_game(self, game: str, ordered_ids: list[str]) -> bool:
        """Reorder one game's accounts to match `ordered_ids`.

        `ordered_ids` must be exactly the set of account ids currently stored
        for `game` (same membership, no extras/missing/duplicates), in the
        desired new order. The other game's entries keep their positions. Pure
        list reordering - no keyring/password/token access. Returns False (no
        change) on any id-set mismatch.
        """
        game_ids = [a["id"] for a in self._accounts
                    if a.get("game", "ttr") == game and a.get("id")]
        if len(ordered_ids) != len(set(ordered_ids)):
            return False  # duplicate id
        if set(ordered_ids) != set(game_ids):
            return False  # missing / extra / foreign id
        by_id = {a["id"]: a for a in self._accounts if a.get("id")}
        new_game_entries = iter(by_id[i] for i in ordered_ids)
        rebuilt = []
        for a in self._accounts:
            # Only real, id-bearing entries of this game are reorderable; an
            # id-less legacy entry stays put (treated like an other-game entry).
            if a.get("game", "ttr") == game and a.get("id"):
                rebuilt.append(next(new_game_entries))
            else:
                rebuilt.append(a)
        self._accounts = rebuilt
        self._save()
        self._emit_change()
        return True

    def reorder(self, old_index: int, new_index: int):
        if 0 <= old_index < len(self._accounts) and 0 <= new_index < len(self._accounts):
            item = self._accounts.pop(old_index)
            self._accounts.insert(new_index, item)
            self._save()

    def clear_all(self) -> list[str]:
        """Delete all stored credentials.

        Returns the list of CC launcher tokens that were stored, so the
        caller can fire best-effort ``/revoke_self`` against the CC API
        for each. Returns an empty list if no CC accounts had tokens
        (or if all accounts were TTR).
        """
        tokens: list[str] = []
        for a in self._accounts:
            account_id = a.get("id")
            game = a.get("game", "ttr")
            if game == "cc" and account_id:
                stored = self.get_launcher_token(account_id)
                if stored:
                    tokens.append(stored)
                    self.clear_launcher_token(account_id)
            if account_id:
                self._delete_password(account_id)
        self._accounts = []
        self._save()
        self._emit_change()
        return tokens
