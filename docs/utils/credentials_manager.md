# utils/credentials_manager.py

## Purpose

Secure credential storage for up to 16 accounts using the OS-native keyring (Secret Service on Linux, Credential Locker on Windows). Account metadata (label, username, game type) is stored in a JSON file; passwords are stored exclusively in the keyring — never written to disk in plaintext.

At 635 lines, this is the most complex utility in the codebase.

---

## Constants

```python
MAX_ACCOUNTS = 16
SERVICE_NAME = "toontown_multitool"
```

---

## Storage Layout

```
~/.config/toontown_multitool/
├── accounts.json     ← metadata only (id, label, username, game)
└── [keyring]         ← passwords, keyed by account UUID
```

Passwords are stored in the keyring under `SERVICE_NAME` + account UUID. They never touch `accounts.json`.

---

## Keyring Probe

Because wallets (KWallet on KDE, GNOME Keyring on GNOME) may require unlocking when the app starts, `CredentialsManager` runs a **two-step probe**:

1. **Step 1 (read)**: Try to read a known probe key. This forces the wallet unlock dialog if the wallet is locked.
2. **Step 2 (write)**: If the key doesn't exist, write it. This also forces unlock and verifies write access.

The probe runs in a background thread (`run_probe(timeout)`). Until it completes, `keyring_probe_pending` is True and `LaunchTab` shows a pending banner.

---

## Class: `CredentialsManager`

### Properties

```python
@property keyring_available: bool     # True if keyring is operational
@property keyring_probe_pending: bool # True while probe is still running
```

### `run_probe(timeout=10.0)`

Starts the two-step probe in a background thread. Sets `keyring_available` and clears `keyring_probe_pending` on completion. On keyring failure, falls back to in-memory storage (passwords lost on app restart, but no crash).

### `_try_keyring_call(func, *args, timeout)` → result | None

Thread-safe keyring call with timeout. Runs `func(*args)` in a `concurrent.futures.ThreadPoolExecutor` with `timeout` seconds. Returns `None` on timeout or exception. All keyring reads/writes go through this to prevent UI hangs from slow or unresponsive wallets.

### v1 Migration

If `~/.config/toontown_multitool/credentials.enc` exists (v1.5 encrypted credential file), `_migrate_from_v1()` decrypts it and moves passwords to the keyring. Runs once; deletes the old file afterward.

`run_deferred_v1_migration()` handles the case where the keyring wasn't available when the app first started — migration runs again when keyring becomes available.

### Backend Recovery

If the primary keyring backend fails to return a password, `_recover_password_from_compatible_backends()` tries other available backends. Useful when the user switches from KWallet to SecretService or vice versa (e.g., desktop environment switch).

`_migrate_password_to_primary_backend()` moves a recovered password to the current primary backend so future reads succeed.

### KWallet Wayland Workaround

`_wake_kwallet_if_relevant()` probes KWallet directly on Wayland+KDE setups where the KWallet daemon may be slow to respond. Called during the probe phase.

### CRUD Methods

```python
get_accounts(game)           → list[AccountCredential]  # with passwords
get_accounts_metadata(game)  → list[AccountCredential]  # metadata only, no password fetch
get_account(index)           → AccountCredential
get_account_metadata(index)  → AccountCredential
count()                      → int
add_account(label, username, password, game)
update_account(index, label, username, password)
delete_account(index)
reorder(old_index, new_index)
clear_all()
```

All write operations update `accounts.json` and the keyring.

`get_accounts()` fetches passwords from the keyring for all accounts in a game — this may be slow if the keyring requires re-unlock. `get_accounts_metadata()` skips password fetches — used when only labels and usernames need displaying.

### Diagnostics

```python
get_backend_diagnostics()   → dict
format_backend_diagnostics() → list[str]
```

Returns info about the active keyring backend, priority, available backends, child backends (for ChainerBackend), and probe status. Displayed in `SettingsTab`.

---

## Dependencies

- `keyring` — OS keyring abstraction (SecretStorage, KWallet, Windows Credential Locker)
- `uuid` — account ID generation
- `json`, `os`, `stat`, `threading` — file I/O, secure deletion, thread safety
- `concurrent.futures` — timeout-safe keyring calls
- `cryptography` — v1 migration decryption (only used once)
- `utils/models.py` — `AccountCredential`

---

## Known Issues / Technical Debt

- At 635 lines, this handles too many concerns: probe, migration, recovery, backend detection, CRUD, diagnostics. Splitting into `KeyringProbe`, `CredentialMigrator`, and `CredentialsManager` would be cleaner.
- The `_try_keyring_call` timeout approach works but creates a thread per keyring call — high volume credential operations would create many threads. Not an issue at current scale (max 16 accounts, infrequent access).
- The fallback in-memory store loses passwords on app restart. Users with broken keyrings must re-enter passwords every launch — not ideal but safe.
