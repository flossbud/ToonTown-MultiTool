# services/cc_login_service.py

## Purpose

Handles the Corporate Clash login flow via HTTP POST to the CC API. Shares the `LoginState` enum from `ttr_login_service.py` for consistency, but the CC response format differs significantly from TTR's.

---

## Constants

```python
CC_API_URL = "https://corporateclash.net/api/v1/login"
CC_HEADERS = {"User-Agent": "ToonTown MultiTool", "Content-Type": "application/json"}
CC_ENGINE_SEARCH_PATHS  # common CC install locations (Windows, Linux, Games folder)
```

---

## Key Differences from TTR Login

| Aspect | TTR | CC |
|--------|-----|-----|
| API URL | toontownrewritten.com | corporateclash.net |
| Request format | form-encoded | JSON |
| `success` field | String ("true"/"false"/"partial"/"delayed") | Boolean |
| Login queue | Yes (`"delayed"` response) | No |
| 2FA | Yes (`"partial"` response, `appToken` field) | Yes (`reason` field triggers, `authToken` submitted) |
| Credentials in response | `gameserver` + `cookie` | `gameserver` + `osst` (OSST token) |

---

## Class: `CCLoginWorker` (QObject)

Same signal interface as `TTRLoginWorker` for UI consistency:

```python
state_changed: Signal(str, str)
queue_update: Signal(int, int)   # unused — CC has no queue
need_2fa: Signal(str)
login_success: Signal(str, str)  # (gameserver, osst_token)
login_failed: Signal(str)
```

### `login(username, password)`

POSTs `{"username": username, "password": password}` as JSON. Parses via `_handle_response()`.

### `_handle_response(data)`

CC API returns `{"status": true/false, "reason": "...", "authToken": "...", "osst": "...", "gameserver": "..."}`:

- `status: true` + `osst` present → emit `login_success(gameserver, osst_token)`
- `status: false` + reason indicates 2FA needed → emit `need_2fa(reason)`, wait for `submit_2fa()`
- `status: false` otherwise → emit `login_failed(reason)`

### `submit_2fa(token)`

Re-POSTs with `{"username": ..., "password": ..., "authToken": token}`. This is the 2FA submission — `authToken` is the TOTP/email code the user enters.

### `cancel()`

Same pattern as `TTRLoginWorker` — sets cancel flag and unblocks any waiting token.

---

## Module Functions

### `find_cc_engine_path()` → str | None

Searches `CC_ENGINE_SEARCH_PATHS` for the CorporateClash binary.

### `get_cc_engine_executable_name()` → str

Returns `"CorporateClash.exe"` on all platforms (CC doesn't have a Linux-specific name distinction in the search paths).

---

## Dependencies

- `requests` — HTTP POST to CC API
- `services/ttr_login_service.py` — imports `LoginState` enum
- `threading` — background login thread
