"""
Machine-bound encrypted credential storage (v2).

Credentials are now stored in the OS-native credential store (e.g. Secret Service
on Linux, Keychain on macOS, Credential Locker on Windows) via the `keyring` library.

The metadata (order, labels, usernames) is kept in a plain JSON config,
while the sensitive part (passwords) is stored in the keyring keyed by a UUID.
"""

import os
import json
import uuid
import keyring

MAX_ACCOUNTS = 8
SERVICE_NAME = "toontown_multitool"


class CredentialsManager:
    """Manages up to 8 TTR account credentials using the system keyring."""

    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self._path = os.path.join(config_dir, "accounts.json")
        self._accounts: list[dict] = []
        
        self._migrate_from_v1(config_dir)
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _migrate_from_v1(self, config_dir):
        old_path = os.path.join(config_dir, "credentials.enc")
        if not os.path.exists(old_path):
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
            
            self._accounts = []
            for acc in old_accounts:
                account_id = str(uuid.uuid4())
                password = acc.get("password", "")
                
                if password:
                    keyring.set_password(SERVICE_NAME, account_id, password)
                
                self._accounts.append({
                    "id": account_id,
                    "label": acc.get("label", ""),
                    "username": acc.get("username", "")
                })
            
            self._save()
            print("[CredentialsManager] Migration successful. Deleting old credentials.enc")
            os.remove(old_path)
            
        except Exception as e:
            print(f"[CredentialsManager] Failed to migrate v1 credentials: {e}")

    def _load(self):
        if not os.path.exists(self._path):
            self._accounts = []
            return
        try:
            with open(self._path, "r") as f:
                self._accounts = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
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

    # ── Read API ───────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        """Return list of accounts. Each: {label, username, password}"""
        result = []
        for a in self._accounts:
            account_id = a.get("id")
            password = ""
            if account_id:
                try:
                    password = keyring.get_password(SERVICE_NAME, account_id) or ""
                except Exception as e:
                    print(f"[CredentialsManager] Failed to get password for {account_id}: {e}")
            
            result.append({
                "label": a.get("label", ""),
                "username": a.get("username", ""),
                "password": password
            })
        return result

    def get_account(self, index: int) -> dict | None:
        if 0 <= index < len(self._accounts):
            a = self._accounts[index]
            account_id = a.get("id")
            password = ""
            if account_id:
                try:
                    password = keyring.get_password(SERVICE_NAME, account_id) or ""
                except Exception:
                    pass
            return {
                "label": a.get("label", ""),
                "username": a.get("username", ""),
                "password": password
            }
        return None

    def count(self) -> int:
        return len(self._accounts)

    # ── Write API ──────────────────────────────────────────────────────────

    def add_account(self, label: str = "", username: str = "", password: str = "") -> bool:
        """Add a new account. Returns False if at capacity."""
        if len(self._accounts) >= MAX_ACCOUNTS:
            return False
            
        account_id = str(uuid.uuid4())
        
        try:
            keyring.set_password(SERVICE_NAME, account_id, password)
        except Exception as e:
            print(f"[CredentialsManager] Failed to set password in keyring: {e}")
            return False
            
        self._accounts.append({
            "id": account_id,
            "label": label,
            "username": username
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
                    try:
                        keyring.set_password(SERVICE_NAME, account_id, password)
                    except Exception as e:
                        print(f"[CredentialsManager] Failed to update password in keyring: {e}")
                        
            self._save()

    def delete_account(self, index: int):
        if 0 <= index < len(self._accounts):
            a = self._accounts.pop(index)
            account_id = a.get("id")
            if account_id:
                try:
                    keyring.delete_password(SERVICE_NAME, account_id)
                except Exception:
                    pass
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
                try:
                    keyring.delete_password(SERVICE_NAME, account_id)
                except Exception:
                    pass
        self._accounts = []
        self._save()