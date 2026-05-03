# utils/win32_backend.py

## Purpose

Windows input backend that sends keystrokes to background game windows using Win32 `PostMessage` with `WM_KEYDOWN` / `WM_KEYUP` messages. This allows background toons to receive input without stealing focus from the foreground window.

Mirrors the `XlibBackend` interface so `InputService` can use either backend interchangeably.

---

## Import Guard

```python
try:
    import win32api, win32con, win32gui, win32process
except ImportError:
    pass
```

The Win32 imports are wrapped in a try/except so the module can be imported on Linux without crashing (the class is never instantiated there). `InputService` selects the backend based on `sys.platform`.

---

## `VK_MAP`

A dict mapping xdotool-style keysym strings to Windows Virtual Key codes (`VK_*` constants):

| Category | Examples |
|----------|---------|
| Special keys | `space`, `Return`, `BackSpace`, `Tab`, `Escape`, `Delete` |
| Arrow keys | `Up`, `Down`, `Left`, `Right` |
| Modifier keys | `Shift_L`, `Shift_R`, `Control_L`, `Control_R`, `Alt_L`, `Alt_R` |
| Numpad | `KP_0`–`KP_9`, `KP_Enter`, `KP_Add`, `KP_Subtract`, etc. |
| OEM keys | `minus` (0xBD), `equal` (0xBB), `bracketleft`, `semicolon`, etc. |
| Digits | `'0'`–`'9'` mapped to `0x30`–`0x39` |
| Letters | `'a'`–`'z'` added programmatically as `ord('A')`–`ord('Z')` |

## `VK_TO_KEYSYM`

Maps raw numpad VK integer values (96–111) to canonical keysym strings (`'KP_0'`–`'KP_9'`, `'KP_Multiply'`, etc.). Used by `InputService` to normalize pynput `KeyCode.vk` values on Windows, since pynput on Windows returns VK codes for numpad keys rather than character names.

---

## Class: `Win32Backend`

### Lifecycle

```python
backend = Win32Backend()
backend.connect()     # no-op (Win32 needs no persistent connection)
backend.disconnect()  # no-op
```

Unlike `XlibBackend`, `Win32Backend` holds no persistent connection. Each `PostMessage` call goes through the Win32 API directly.

---

## Methods

### `get_window_x(win_id_str) → int | None`

Calls `win32gui.GetWindowRect(hwnd)` and returns `rect[0]` (left edge X coordinate). Used by `WindowManager` to determine slot ordering.

### `get_window_pid(win_id_str) → int | None`

Calls `win32process.GetWindowThreadProcessId(hwnd)` and returns the PID. Used by `GameRegistry` and `ttr_api` for game-type classification.

### `_get_vk(keysym_str) → int | None`

Resolves a keysym string to a VK code:
1. Direct lookup in `VK_MAP`.
2. For single-character strings not in `VK_MAP`, tries `win32api.VkKeyScan(char) & 0xFF`.
3. Returns `None` if lookup fails.

### `_send(win_id_str, msg, vk) → bool`

Core send method:
1. Calculates `scan_code = win32api.MapVirtualKey(vk, 0)`.
2. Constructs `lparam`:
   - Bits 0–15: repeat count (always 1)
   - Bits 16–23: scan code
   - For `WM_KEYUP`: bit 30 (previous key state) and bit 31 (transition state) are set per Win32 spec.
3. Calls `win32gui.PostMessage(hwnd, msg, vk, lparam)`.

`PostMessage` is asynchronous — it places the message in the window's message queue without waiting for it to be processed. This is intentional: the caller continues without blocking.

### `send_keydown(win_id_str, keysym_str, state=0) → bool`

Sends `WM_KEYDOWN`.

### `send_keyup(win_id_str, keysym_str, state=0) → bool`

Sends `WM_KEYUP`.

### `send_key(win_id_str, keysym_str, modifiers=None) → bool`

Sends a complete keystroke sequence: modifier downs → key down → key up → modifier ups. Modifiers are mapped via `mod_map = {"shift": "Shift_L", "ctrl": "Control_L", "alt": "Alt_L"}`.

### `sync()`

No-op on Windows. Exists for interface symmetry with `XlibBackend.sync()`.

---

## Dependencies

- `win32api`, `win32con`, `win32gui`, `win32process` (pywin32 package, Windows only)

---

## Known Issues / Technical Debt

- `state` parameter in `send_keydown` / `send_keyup` is accepted but unused — Win32 key messages don't use an explicit state mask the same way X11 does. Modifier state is implicit from which modifier keys are down in the message queue.
- `VK_TO_KEYSYM` is defined here but consumed by `InputService`. The tight coupling between the two files means changes to the numpad normalization must be coordinated.
- `send_key()` sends all modifier-up messages in reversed order, which is correct behavior for properly nesting modifier releases but is undocumented.
- Some games ignore `PostMessage` for movement because they use raw input rather than the message queue. TTR and CC both accept message-queue input, so this works in practice.
