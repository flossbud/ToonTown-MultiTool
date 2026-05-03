# utils/settings_manager.py

## Purpose

Singleton-style settings store for all persistent app preferences. Persists to `~/.config/toontown_multitool/settings.json`. Provides a change-notification callback system so UI components can react to setting changes without polling.

---

## Storage

```
~/.config/toontown_multitool/settings.json
```

---

## Default Settings

```python
{
    "show_debug_tab":        False,
    "show_diagnostics_tab":  False,
    "keep_alive_action":     "jump",
    "keep_alive_delay":      "30 sec",
    "theme":                 "system",
    "enable_companion_app":  True,
    "input_backend":         "xlib",
    "active_profile":        -1,
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `show_debug_tab` | False | Whether the debug/logs tab is visible in the sidebar. |
| `show_diagnostics_tab` | False | Whether the diagnostics tab is visible. |
| `keep_alive_action` | `"jump"` | Key action for keep-alive: `"jump"`, `"book"`, etc. |
| `keep_alive_delay` | `"30 sec"` | Keep-alive interval, stored as display string. |
| `theme` | `"system"` | `"dark"`, `"light"`, or `"system"` (auto-detect from OS). |
| `enable_companion_app` | True | Whether TTR Companion App API polling is enabled. |
| `input_backend` | `"xlib"` | `"xlib"` (Linux default) or `"win32"` (Windows). |
| `active_profile` | -1 | Index of currently loaded profile, -1 = none. |

---

## Class: `SettingsManager`

### `_load()`

Reads JSON and merges into the defaults dict using `dict.update()`. This means:
- New keys added in future versions have their defaults automatically applied to old configs.
- Unknown keys in old files are ignored (they don't cause errors, but also don't persist on next save).

### `save()`

Writes the full settings dict to JSON. Uses `f.flush()` + `os.fsync(f.fileno())` for durability — guarantees settings are on disk even if the app crashes or is killed immediately after. More aggressive than `ProfileManager._save()` because settings affect the next launch's behavior.

### `get(key, default=None)`

Simple dict lookup with fallback.

### `set(key, value)`

Updates the in-memory dict, saves immediately, then fires all registered callbacks with `(key, value)`. Exceptions in callbacks are silently swallowed to prevent one bad subscriber from breaking others.

### `on_change(callback)`

Registers a `callback(key, value)` to be called on every `set()`. Used by:
- `CreditsTab`, `KeepAliveTab`, `SettingsTab`, `MultitoonTab` — theme change
- `DebugTab` — show/hide tab toggle
- `InputService` — backend switching, keep-alive action/delay
- Various tabs — companion app enable/disable

---

## Module-level helper: `safe_get_theme(settings_manager)`

Returns the current theme string, falling back to `"dark"` if `settings_manager` is `None`. Used during early initialization when components may be constructed before the settings manager is available.

---

## Dependencies

- `os`, `json`

---

## Known Issues / Technical Debt

- No thread safety — `set()` is called from the main Qt thread and callbacks run synchronously in the same call. If a background thread ever calls `set()`, there's a race condition with `_callbacks` list iteration.
- Callbacks list grows but never shrinks. If a subscriber is destroyed but not unregistered, the dead callback is still called on every `set()`. No mechanism to unregister.
- `active_profile` is stored here rather than in `ProfileManager`, coupling these two modules implicitly.
