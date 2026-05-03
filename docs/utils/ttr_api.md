# utils/ttr_api.py

## Purpose

Client for the TTR Local (Companion App) API. Each running TTR instance exposes an HTTP server on a port in the range 1547–1552, serving `/all.json` with the logged-in toon's name, laff, max laff, bean count, and visual style/color DNA. This module fetches that data, correlates it with game window IDs, and returns results ordered by toon slot.

---

## Architecture

```
Port scan (ss/netstat) → port→PID map
XRes extension         → windowID→PID map
PID join               → port→windowID map (stable cache)
/all.json fetch        → port→toon data
Slot assignment        → current_window_ids[i] → data[i]
```

---

## Module Constants

```python
TTR_API_PORT_START = 1547
TTR_API_PORT_END   = 1552
TTR_API_HOSTS      = ["::1", "127.0.0.1"]   # IPv6 preferred, IPv4 fallback
TTR_USER_AGENT     = "ToonTown MultiTool"
_AUTH_TOKEN        = secrets.token_hex(16)   # random per-session auth token
```

The `Authorization` header is required by the TTR API. A random 32-char hex token is generated at import time — TTR accepts any non-empty token value.

---

## Logging

```python
set_debug(enabled)          # enable/disable verbose per-port logging
set_log_callback(callback)  # route log output to debug tab instead of terminal
```

When debug is enabled, log messages are emitted only when values change (`_last_logged` dict), preventing log spam on every 5-second fetch cycle.

---

## `_fetch_toon(port, timeout) → dict | None`

Queries `/all.json` on the given port. Tries IPv6 (`[::1]`) first, then IPv4 (`127.0.0.1`). Returns the parsed JSON dict or `None` on any failure. TTR uses IPv6 loopback by default on Linux.

---

## Port → Window ID Mapping

### `_build_port_to_window_id(current_window_ids, active_ports)`

Builds a stable `{port: window_id}` mapping. Results are cached by fingerprint (frozen set of window IDs + active ports + approved ports). Only recomputes when the window set or port set changes.

**Step 1 — Port → Host PID:**
- **Linux**: Runs `ss -tlnp`, parses lines matching `TTREngine` to extract port and PID.
- **Windows**: Runs `netstat -ano`, filters `LISTENING` entries in the 1547–1552 range.

**Step 2 — Window → Host PID:**
- **Linux**: Tries XRes extension first (`_get_window_pids_xres`). Falls back to NSpid mapping via `/proc/{pid}/status` + `xdotool getwindowpid` (`_get_window_pids_nspid`).
- **Windows**: Uses `win32process.GetWindowThreadProcessId` for each HWND.

XRes is preferred because it returns the real host PID even for Flatpak-containerized TTR instances. NSpid mapping breaks when multiple Flatpak instances share the same namespace PID.

**Step 3 — Join:**
Matches ports to windows via the shared PID. Multiple windows per PID (possible on Windows) are assigned to ports in stable sorted order.

### `invalidate_port_to_wid_cache()`

Forces a full rebuild on the next fetch. Called by `MultitoonTab` when windows are added/removed.

### `_get_window_pids_nspid(window_ids, host_pids)`

Fallback PID resolution:
1. Reads `/proc/{host_pid}/status` to extract namespace PID (NSpid line).
2. Runs `xdotool getwindowpid` to get the namespace-visible PID for each window.
3. Joins: namespace_pid → host_pid → window_id.

This fails for Flatpak because all instances may share the same NSpid, making the join ambiguous.

---

## Smart Port Scanning (Fix #7)

### Problem

On each fetch cycle (every 5s), scanning all 6 ports meant spawning 6 threads even when the same ports respond every time.

### Solution

```python
_approved_ports: set     # ports that have successfully responded at least once
_FULL_SCAN_COOLDOWN = 30.0   # seconds between forced full scans
```

`_should_full_scan()` returns `True` if:
- No approved ports yet (first scan)
- Window set has changed (new instance launched or closed)
- 30 seconds have elapsed since last full scan

Otherwise, only approved ports are queried (fast path, 0.5s timeout vs 5.0s).

After a full scan, `_approved_ports` is pruned to only ports that responded, keeping the approved set current as toons log out.

---

## Window → Name Cache

```python
_wid_to_name: dict      # window_id → toon name
_wid_to_style: dict     # window_id → Rendition DNA string
_wid_to_color: dict     # window_id → headColor hex string
_wid_to_laff: dict
_wid_to_max_laff: dict
_wid_to_beans: dict
```

All caches are protected by `_wid_to_name_lock`. On each fetch:
- Active windows with data are updated.
- Windows that are open but no longer returning API data (e.g., logged out to main menu) are cleared.

### `clear_stale_names(current_window_ids)`

Removes cache entries for windows that no longer exist. Called when `WindowManager` reports a window closed.

---

## Public API

### `get_toon_names_by_slot(num_slots, current_window_ids) → (names, styles, colors, laffs, max_laffs, beans)`

Synchronous fetch. Spawns one thread per port being scanned, joins with a 6s timeout. Returns 6 lists of length `num_slots`, ordered by `current_window_ids` index. `None` at a position means no data for that slot.

**Fallback mapping:** If the XRes/NSpid join produces fewer mappings than expected (e.g., one port was scanned but the XRes query failed for one window), remaining unmatched ports are paired with remaining unmatched windows in sorted order. This is a best-effort heuristic for degraded environments.

### `get_toon_names_threaded(num_slots, callback, current_window_ids=None)`

Calls `get_toon_names_by_slot` in a daemon thread. `callback(names, styles, colors, laffs, max_laffs, beans)` is called on completion. This is the function `MultitoonTab` calls every 5 seconds.

---

## Dependencies

- `http.client`, `json`, `re`, `secrets`, `subprocess`, `threading`, `time` — stdlib only
- `Xlib`, `Xlib.ext.res` — Linux XRes PID resolution
- `win32process` — Windows window→PID resolution

---

## Known Issues / Technical Debt

- The `ss -tlnp` regex (`TTREngine.*pid=(\d+)`) is fragile — it assumes the process name appears in the ss output on the same line as the port. If the TTR engine executable name changes, this breaks silently (returns empty mapping).
- The 6s join timeout in `get_toon_names_by_slot` means a slow query cycle can block the calling thread for up to 6 seconds. `MultitoonTab` calls this from a background thread, so the UI doesn't freeze, but the data update can be delayed.
- `_AUTH_TOKEN` is regenerated every process launch. TTR accepts any token, so this is fine, but if TTR ever validates tokens across sessions, this would break.
- Port→window mapping is built inside `_port_to_wid_lock` but the fingerprint check and cache read also hold the lock for the duration of the rebuild. Under high contention (unlikely at current scale), this could stall the fetch thread.
