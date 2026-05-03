# services/hotkey_manager.py

## Purpose

Global keyboard hotkey listener. Captures keyboard events system-wide (via pynput), normalizes keys into X11 keysym strings, pushes them into the input service event queue, and handles Ctrl+1–5 profile loading hotkeys. Extracted from `main.py` in v2 for cleaner separation.

---

## Signals

```python
profile_load_requested: Signal(int)  # emitted with 0-based profile index on Ctrl+1-5
```

---

## Class-Level Constants

### `PYNPUT_VK_MAP`

Maps Windows virtual key codes (VK_NUMPAD0–9, VK_DECIMAL, etc.) to X11 keysym strings. Checked **before** pynput name maps because on Windows, numpad keys and regular keys can share the same `key.name` (e.g., numpad 0 and Insert both produce `"insert"` from pynput), but have distinct VK codes. Checking VK first disambiguates them.

### `PYNPUT_NAME_MAP`

Maps pynput key name strings (e.g., `"space"`, `"enter"`, `"shift_l"`) to X11 keysym strings. The canonical mapping used when VK lookup doesn't apply.

---

## `__init__`

Takes `window_manager` (for focus-based start/stop logic) and `key_event_queue` (the queue shared with `InputService`).

Connects to `window_manager.active_window_changed` → `_on_active_window_changed`.

---

## `start()` / `stop()`

`start()` checks `window_manager.should_capture_input()` and starts the listener if appropriate. `stop()` stops the listener and clears the `pressed_keys` set.

---

## `_on_active_window_changed(active_win_id)`

Called whenever focus changes. Dynamically starts or stops the pynput listener:
- If game or MultiTool is focused → start listener (if not already running)
- Otherwise → stop listener

This "focus-aware" approach means the global hotkey listener only runs when relevant, reducing unnecessary interception of other application keypresses.

---

## `_start_listener()` / `_stop_listener()`

Start/stop the `pynput.keyboard.Listener`. The listener runs on its own thread (managed by pynput). `_stop_listener` calls `listener.stop()` and joins the thread.

---

## `normalize_key(key)` → str | None

Converts a pynput key object to an X11 keysym string. Resolution order:

1. **VK code** (Windows only): If `key.vk` is in `PYNPUT_VK_MAP`, return that mapping. This handles numpad disambiguation.
2. **Character**: If `key.char` is set, return `key.char.lower()` for alpha, else `key.char`.
3. **Name**: If `key.name` is set, look up in `PYNPUT_NAME_MAP`.

Returns `None` if no mapping found — callers skip these keys.

---

## `on_global_key_press(key)` / `on_global_key_release(key)`

The pynput callback methods (run on pynput's listener thread).

**Key press:**
1. Tracks Ctrl state in `pressed_keys`
2. Checks for Ctrl+1–5: if matched, emits `profile_load_requested(index)` via `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` — the queued connection is critical because pynput runs on a non-Qt thread; direct signal emission from here would be unsafe.
3. Normalizes the key and puts `("keydown", key_str)` in the event queue for `InputService`

**Key release:**
1. Updates `pressed_keys` (removes Ctrl)
2. Puts `("keyup", key_str)` in the event queue

Both handlers wrap everything in `try/except Exception: pass` — exceptions in pynput callbacks silently kill the listener thread if unhandled.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `pynput.keyboard` | Global key listener |
| `services/window_manager.py` | Focus-based start/stop |
| `queue` | Event queue shared with InputService |
| `PySide6.QtCore.QMetaObject` | Thread-safe signal emit for profile loading |

---

## Known Issues / Technical Debt

- VK maps are Windows-only but the class is instantiated on Linux too — `PYNPUT_VK_MAP` is only useful on Windows; on Linux, `key.vk` is typically None so the first check is always skipped.
- The `pressed_keys` set only tracks Ctrl state manually. This is a simplified approach — a more general modifier tracking would be needed if more complex hotkey combinations were added.
