# utils/game_registry.py

## Purpose

Singleton registry that maps running game process PIDs to their game type (`"ttr"` or `"cc"`). Used by `WindowManager` to correctly classify discovered windows, and by `ttr_api` to decide which API to call for a given window. Without this, a system running both TTR and CC simultaneously would confuse window detection.

---

## Singleton Pattern

```python
GameRegistry.instance()  # returns the single shared instance
```

The instance is created on first call and reused thereafter. Thread-safe via `threading.Lock`.

---

## Module Constants

```python
_KNOWN_PROCESSES = {
    "ttrengine": "ttr",
    "ttrengine64.exe": "ttr",
    "corporateclash": "cc",
    "corporateclash.exe": "cc",
}
```

Maps lowercase executable basename → game type. Used as a fallback when a window's PID wasn't registered (e.g., externally launched instances not started through `LaunchTab`).

---

## Methods

### `register(pid, game)` / `unregister(pid)`

Called by `TTRLauncher` / `CCLauncher` when a game is launched/exits. Maintains `_pid_to_game: dict[int, str]`.

### `get_game(pid)` → str | None

Returns `"ttr"` or `"cc"` for a registered PID, or `None` if not registered. Falls back to `_tag_from_process_name(pid)` if unregistered.

### `get_game_for_window(wid)` → str | None

Resolves window ID → PID → game type. Uses `_get_pid_for_window(wid)` then `get_game()`.

### `classify_window_for_filtering(wid)` → tuple[str | None, bool]

Returns `(game_type, confirmed)`:
- `confirmed = True` if identity resolved via registered PID or XRes (reliable)
- `confirmed = False` if resolved via process name heuristic (less reliable)

`WindowManager` uses `confirmed` to decide whether to include a window unconditionally or apply additional heuristics (size/style checks).

### `_get_pid_for_window(wid)` → int | None

**Linux**: Prefers `_get_host_pid_for_window_xres(wid)` (XRes extension). Falls back to `xdotool getwindowpid`. Falls back further to reading `/proc/{pid}/exe` for the executable name.

**Windows**: `win32process.GetWindowThreadProcessId(hwnd)`.

### `_get_host_pid_for_window_xres(wid)` → int | None

Uses Xlib's XRes extension (`XRes.GetClientPid`) to get the host PID for a window without going through `/proc/NSpid` namespace resolution. More reliable than xdotool for Flatpak containers.

### `_tag_from_process_name(pid)` → str | None

Reads `/proc/{pid}/exe` (Linux) or `win32api.GetModuleFileNameEx` (Windows) to get the executable name, then looks it up in `_KNOWN_PROCESSES`.

---

## Dependencies

- `sys`, `threading`, `subprocess`, `os`
- `Xlib` (Linux, XRes extension)
- `win32api`, `win32process` (Windows)

---

## Known Issues / Technical Debt

- Singleton global state makes testing harder — a reset method would help for unit tests.
- `_tag_from_process_name()` reads `/proc/{pid}/exe` which requires the process still be running. Race condition if a process exits between window detection and name lookup.
