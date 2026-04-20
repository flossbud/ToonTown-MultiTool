"""
Machine-bound encrypted credential storage (v2).

Credentials are now stored in the OS-native credential store (e.g. Secret Service
on Linux, Keychain on macOS, Credential Locker on Windows) via the `keyring` library.

The metadata (order, labels, usernames) is kept in a plain JSON config,
while the sensitive part (passwords) is stored in the keyring keyed by a UUID.
"""

import os
import json
import stat
import time
import uuid
import threading
import keyring
import keyring.backend

from utils.models import AccountCredential

MAX_ACCOUNTS = 16
SERVICE_NAME = "toontown_multitool"


class CredentialsManager:
    """Manages up to 8 TTR account credentials using the system keyring."""

    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
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

        self._cleanup_legacy_fallback_file()
        
        self._migrate_from_v1(config_dir)
        self._load()

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
                print(f"[CredentialsManager] Failed to remove legacy v1 file: {e}")
            return

        if not self.keyring_available:
            self._deferred_v1_migration = True
            print("[CredentialsManager] Keyring unavailable or probe pending; deferring v1 credential migration.")
            return

        print("[CredentialsManager] Migrating credentials from v1 to keyring...")
        
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
                print("[CredentialsManager] Migration successful. Old file archived as .migrated")
            except Exception as e:
                print(f"[CredentialsManager] Warning: could not archive old credentials: {e}")

            self._deferred_v1_migration = False
            
        except Exception as e:
            print(f"[CredentialsManager] Failed to migrate v1 credentials: {type(e).__name__}")

    def _load(self):
        if not os.path.exists(self._path):
            self._accounts = []
            return
        try:
            with open(self._path, "r") as f:
                self._accounts = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[CredentialsManager] Failed to load accounts: {e}")
            self._accounts = []

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._accounts, f, indent=4)
            # Restrict file permissions
            os.chmod(self._path, 0o600)
        except Exception as e:
            print(f"[CredentialsManager] Failed to save accounts: {e}")

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
                print(f"[CredentialsManager] Failed to delete legacy fallback password store: {type(e).__name__}")
                self._legacy_fallback_deleted = False
        else:
            self._legacy_fallback_deleted = False

    def run_probe(self, timeout: float = 45.0) -> bool:
        """
        Probe the keyring from a background thread.

        Two-step: read the probe key, then write it if it doesn't exist yet.
        Either step forces the wallet unlock dialog (if the wallet is locked),
        giving the user up to `timeout` seconds to respond. Once the wallet is
        open it stays open for the session, so subsequent _get_password calls
        (which use a short 1.5s timeout) succeed without re-prompting.
        """
        # Step 1: read the probe key. Forces wallet unlock if key exists.
        ok, value = self._try_keyring_call(
            keyring.get_password, SERVICE_NAME, "__ttmt_probe__", timeout=timeout
        )
        if not ok:
            self._use_keyring = False
            self._probe_complete = True
            print("[CredentialsManager] Keyring unavailable/unresponsive; passwords will not be saved between sessions.")
            return False

        if value is None:
            # Probe key doesn't exist yet — write it. Writing to a locked wallet
            # forces the unlock dialog, so this serves the same purpose as a read
            # on an existing key. After this, the wallet is open for the session.
            ok, _ = self._try_keyring_call(
                keyring.set_password, SERVICE_NAME, "__ttmt_probe__", "1", timeout=timeout
            )
            if not ok:
                # Write failed — user likely dismissed the unlock dialog.
                self._use_keyring = False
                self._probe_complete = True
                print("[CredentialsManager] Keyring write failed (wallet dismissed?); passwords will not be saved between sessions.")
                return False

        self._wake_kwallet_if_relevant(timeout)
        self._use_keyring = True
        self._probe_complete = True
        self._primary_backend_name = self._detect_primary_backend_name()
        if self._deferred_v1_migration:
            self.run_deferred_v1_migration()
        return True

    def run_deferred_v1_migration(self):
        if self._deferred_v1_migration and self.keyring_available:
            self._migrate_from_v1(os.path.dirname(self._path))

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
                print("[CredentialsManager] Keyring call timed out; passwords will not be saved between sessions.")
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
                raise result["error"]
            return True, result["value"]
        except Exception as e:
            self._use_keyring = False
            self._probe_complete = True
            print(
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
                backend, "get_password", SERVICE_NAME, "__ttmt_probe__", timeout=1.5
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
            if backend_name != "keyring.backends.kwallet.DBusKeyring":
                continue
            ok, value = self._call_backend_method(
                backend, "get_password", SERVICE_NAME, "__ttmt_probe__", timeout=timeout
            )
            if ok:
                state = "value-present" if value else "value-empty-or-none"
                print(f"[Credentials] Direct KWallet probe succeeded [{state}].")
            else:
                print("[Credentials] Direct KWallet probe failed or timed out.")
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
                backend, "set_password", SERVICE_NAME, account_id, password, timeout=2.0
            )
            if ok:
                print(
                    f"[Credentials] Recovered password from {source_backend_name} "
                    f"and migrated it to {target_name}."
                )
            return

    def _recover_password_from_compatible_backends(self, account_id: str) -> str:
        cumulative_timeout = 5.0
        start = time.monotonic()
        for backend in self._available_explicit_backends():
            if time.monotonic() - start > cumulative_timeout:
                print(f"[Credentials] Backend recovery timed out after {cumulative_timeout}s.")
                break
            backend_name = self._backend_name(backend)
            remaining = max(0.5, cumulative_timeout - (time.monotonic() - start))
            ok, value = self._call_backend_method(
                backend, "get_password", SERVICE_NAME, account_id, timeout=min(1.5, remaining)
            )
            if ok and value:
                self._migrate_password_to_primary_backend(account_id, value, backend_name)
                print(f"[Credentials] Recovered password via {backend_name}.")
                return value
        return ""

    def _get_password(self, account_id: str) -> str:
        if not account_id:
            return ""
        ok, value = self._try_keyring_call(keyring.get_password, SERVICE_NAME, account_id, timeout=1.5)
        if ok:
            if value:
                return value
            if self._probe_complete:
                recovered = self._recover_password_from_compatible_backends(account_id)
                if recovered:
                    return recovered
            return ""
        if self._probe_complete:
            recovered = self._recover_password_from_compatible_backends(account_id)
            if recovered:
                return recovered
        with self._fallback_lock:
            entry = self._fallback_passwords.get(account_id)
            if entry:
                password, timestamp = entry
                if time.monotonic() - timestamp > self._fallback_max_age:
                    del self._fallback_passwords[account_id]
                    print(f"[Credentials] In-memory password expired.")
                    return ""
                return password
        return ""

    def _set_password(self, account_id: str, password: str) -> bool:
        if not account_id:
            return False
        ok, _ = self._try_keyring_call(keyring.set_password, SERVICE_NAME, account_id, password, timeout=1.5)
        if ok:
            with self._fallback_lock:
                self._fallback_passwords.pop(account_id, None)
            return True
        with self._fallback_lock:
            self._fallback_passwords[account_id] = (password or "", time.monotonic())
        print(f"[Credentials] WARNING: Password stored in volatile memory (keyring unavailable). "
              f"It will be cleared after {self._fallback_max_age // 60} minutes or on restart.")
        return True

    def _delete_password(self, account_id: str):
        if not account_id:
            return
        self._try_keyring_call(keyring.delete_password, SERVICE_NAME, account_id, timeout=1.5)
        with self._fallback_lock:
            self._fallback_passwords.pop(account_id, None)

    @property
    def keyring_available(self) -> bool:
        return self._probe_complete and self._use_keyring

    @property
    def keyring_probe_pending(self) -> bool:
        return not self._probe_complete

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
                    probe_status = "not-tested"
                    probe_detail = ""
                    try:
                        value = child.get_password(SERVICE_NAME, "__ttmt_probe__")
                        probe_status = "ok"
                        probe_detail = "value-present" if value else "value-empty-or-none"
                    except Exception as e:
                        probe_status = "error"
                        probe_detail = f"{type(e).__name__}: {e}"
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
                print(f"[CredentialsManager] Warning: skipping account with missing ID: {a.get('label', '?')}")
                continue
            password = self._get_password(account_id)

            result.append(AccountCredential.from_dict(a, password))
        return result

    def get_accounts_metadata(self, game: str | None = None) -> list[AccountCredential]:
        """Return account metadata without fetching passwords."""
        result = []
        for a in self._accounts:
            if game is not None and a.get("game", "ttr") != game:
                continue
            result.append(AccountCredential.from_dict(a, password=""))
        return result

    def get_account(self, index: int) -> AccountCredential | None:
        if 0 <= index < len(self._accounts):
            a = self._accounts[index]
            account_id = a.get("id")
            password = self._get_password(account_id) if account_id else ""
            return AccountCredential.from_dict(a, password)
        return None

    def get_account_metadata(self, index: int) -> AccountCredential | None:
        """Return account metadata without fetching the password."""
        if 0 <= index < len(self._accounts):
            return AccountCredential.from_dict(self._accounts[index], password="")
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

        self._accounts.append({
            "id": account_id,
            "label": label,
            "username": username,
            "game": game,
        })
        self._save()
        return True

    def update_account(self, index: int, label: str = None, username: str = None, password: str = None):
        """Update specific fields of an account."""
        if 0 <= index < len(self._accounts):
            a = self._accounts[index]
            
            if label is not None:
                a["label"] = label
            if username is not None:
                a["username"] = username
            if password is not None:
                account_id = a.get("id")
                if account_id:
                    self._set_password(account_id, password)
                        
            self._save()

    def delete_account(self, index: int):
        if 0 <= index < len(self._accounts):
            a = self._accounts.pop(index)
            account_id = a.get("id")
            if account_id:
                self._delete_password(account_id)
            self._save()

    def reorder(self, old_index: int, new_index: int):
        if 0 <= old_index < len(self._accounts) and 0 <= new_index < len(self._accounts):
            item = self._accounts.pop(old_index)
            self._accounts.insert(new_index, item)
            self._save()

    def clear_all(self):
        """Delete all stored credentials."""
        for a in self._accounts:
            account_id = a.get("id")
            if account_id:
                self._delete_password(account_id)
        self._accounts = []
        self._save()
