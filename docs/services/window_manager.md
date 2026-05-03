# services/window_manager.py

## Purpose

Detects and manages game (TTR/CC) windows, tracks active window focus, and provides the window ID list used by `InputService` for input routing. In v2, window management was extracted from `InputService` into this dedicated service, adding cross-platform support (Linux xdotool + Windows win32gui).

---

## Signals

```python
window_ids_updated: Signal(list)   # emitted when window list changes
active_window_changed: Signal(str) # emitted when focused window changes
```

`active_window_changed` emits the window ID string of the newly focused window, or an empty string if focus moved to an unrecognized window.

---

## Class: `WindowManager` (QObject)

### State

```python
_window_ids: list       # sorted list of game window ID strings
_active_window: str     # currently focused window ID
_detection_enabled: bool
_lock: threading.Lock
```

### `start()` / `stop()`

Starts/stops the polling thread. The thread is daemonic — no cleanup needed on exit. `stop()` sets `_running = False` and joins the thread.

### `enable_detection()` / `disable_detection()`

`enable_detection()` flips `_detection_enabled = True` and calls `assign_windows()` immediately. `disable_detection()` flips it False and clears the window list (emits `window_ids_updated([])` to notify consumers).

### `get_window_ids()` → list

Thread-safe copy of `_window_ids`. Used by `InputService` to get current targets.

### `get_active_window()` → str

Thread-safe read of `_active_window`.

### `_poll_loop()`

The background thread target. Runs continuously:
1. Every 0.1s: reads the active window and emits `active_window_changed` if it changed
2. Every 2s: calls `assign_windows()` to refresh the window list (catches new/closed windows)

The 2-second window re-assignment interval is separate from the 100ms active window poll — window enumeration is more expensive than a single `getactivewindow` call.

### `assign_windows()`

Discovers game windows and sorts them left-to-right:

**Linux path:**
1. `xdotool search --class "Toontown Rewritten"` and `xdotool search --class "Corporate Clash"` (or equivalent class names)
2. For each window: `xdotool getwindowgeometry` to get X position
3. Uses `GameRegistry.classify_window_for_filtering()` to confirm game type
4. Sorts by X position (stable slot assignment matching visual layout)
5. Caps at discovered window count (no fixed limit in v2, unlike v1.5's hardcoded 4)

**Windows path:**
1. `win32gui.EnumWindows()` to iterate all top-level windows
2. Filters by: visible (`IsWindowVisible`), non-child (`GetParent == 0`), non-tool window (no `WS_EX_TOOLWINDOW` style), minimum size 300×200
3. Uses `GameRegistry` to confirm game type from window title/class
4. Sorts by X position

Emits `window_ids_updated` only if the list changed (prevents spurious API cache invalidation).

### `is_multitool_active()` → bool

Returns True if the active window ID matches the stored MultiTool window ID (from settings). Used by `HotkeyManager` and `InputService`.

### `is_ttr_active()` → bool

Returns True if any known game window is currently active.

### `should_capture_input()` → bool

Returns True if `is_ttr_active()` OR `is_multitool_active()`. This is the gate that `InputService.should_send_input()` delegates to.

### `@property active_window_id`

Thread-safe property alias for `get_active_window()`.

### `clear_window_ids()`

Clears `_window_ids` and emits `window_ids_updated([])`. Called by `disable_detection()`.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/game_registry.py` | Classify windows as TTR/CC |
| `subprocess` | Linux: xdotool calls |
| `win32gui`, `win32con` | Windows: window enumeration |
| `threading`, `time` | Polling thread, lock |

---

## Known Issues / Technical Debt

- Window class names for CC are not guaranteed stable across CC updates — if CC changes `WM_CLASS`, Linux detection breaks silently.
- The 2-second re-assignment interval means a newly launched game window takes up to 2 seconds to appear in the slot list. No event-driven alternative exists cross-platform.
- On Windows, `EnumWindows` includes overlay and system windows that need filtering — the current filters (size, style) are heuristic and could potentially include non-game windows in edge cases.
