# services/ttr_login_service.py

## Purpose

Handles the full Toontown Rewritten login flow: HTTP login POST, queue polling (with exponential backoff), and 2FA token submission. Also provides utilities for discovering the TTREngine binary path across different installation methods.

---

## Constants

```python
API_URL = "https://www.toontownrewritten.com/api/login?format=json"
HEADERS = {"User-Agent": "ToonTown MultiTool", "Content-Type": "application/x-www-form-urlencoded"}
ENGINE_SEARCH_PATHS  # common install locations (Flatpak, native, Windows Games folder, Program Files)
```

---

## Class: `LoginState`

Enum of login states:
- `IDLE` — not logged in
- `LOGGING_IN` — login POST in progress
- `NEED_2FA` — waiting for user to submit 2FA token
- `QUEUED` — in TTR login queue
- `LAUNCHING` — credentials received, game launching
- `RUNNING` — game process running
- `FAILED` — error

---

## Class: `TTRLoginWorker` (QObject)

Manages a single TTR account login session. Each account in `LaunchTab` gets its own `TTRLoginWorker`.

### Signals

```python
state_changed: Signal(str, str)    # (state, human-readable message)
queue_update: Signal(int, int)     # (position, eta_seconds)
need_2fa: Signal(str)              # (banner_prompt from TTR API)
login_success: Signal(str, str)    # (gameserver, cookie)
login_failed: Signal(str)          # (error_message)
```

### `login(username, password)`

Starts a background thread that POSTs to `API_URL` with `username` and `password` form fields. Parses the response via `_handle_response()`.

### `_handle_response(data)`

Parses TTR's JSON response. The `success` field is a string (not bool):

| `success` value | Meaning | Action |
|----------------|---------|--------|
| `"true"` | Login succeeded immediately | Emit `login_success(gameserver, cookie)` |
| `"false"` | Login failed | Emit `login_failed(reason)` |
| `"partial"` | 2FA required | Emit `need_2fa(banner)`, wait for `submit_2fa()` |
| `"delayed"` | In login queue | Start `_start_queue_polling()` |

### `submit_2fa(token)`

Thread-safe token delivery via `_token_lock`. The waiting login thread reads this token and re-submits the POST with the `appToken` field.

### `_start_queue_polling()`

Polls the TTR API every 10 seconds (within TTR's 30s rate limit) until the queue resolves:
- Max 60 polls (10 minutes)
- Exponential backoff on network errors (2s → 4s → max 5s)
- Stops after 10 consecutive network failures
- Emits `queue_update(position, eta)` each poll

The queue token from the initial "delayed" response is included in subsequent POSTs via `queueToken` field.

### `_parse_queue_int(value, default)` → int

Safely converts a queue position or ETA value from the API response to int, returning `default` if conversion fails. TTR's queue fields are integers but may be missing or malformed.

### `cancel()`

Sets a cancel flag; the running thread checks it and exits. Also delivers an empty token string to unblock any waiting `submit_2fa()`.

---

## Module Functions

### `find_engine_path()` → str | None

Searches `ENGINE_SEARCH_PATHS` for the TTREngine binary. Returns the first found path, or `None`. Used by `TTRLauncher` when no custom path is configured.

### `get_engine_executable_name()` → str

Returns `"TTREngine64.exe"` on Windows, `"TTREngine"` on Linux. Used in path searches.

---

## Dependencies

- `requests` — HTTP POST to TTR API
- `threading`, `time` — background thread, queue polling
- No internal dependencies (intentionally isolated)

---

## Known Issues / Technical Debt

- The 10-second queue poll interval is hardcoded. TTR's API allows up to 30-second intervals; polling faster than needed doesn't hurt but wastes a thread.
- `requests` is a dependency; for a utility that only makes simple HTTP POSTs, `http.client` (stdlib) would suffice and reduce the dependency footprint.
- The `submit_2fa` thread-safe token delivery uses a `_token_lock` + blocking wait — if the login thread crashes, the 2FA wait hangs. A timeout would be safer.
