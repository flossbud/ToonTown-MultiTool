# utils/xlib_backend.py

## Purpose

Linux input backend that sends keystrokes to background X11 windows using direct Xlib `send_event` calls. Replaces the previous approach of spawning `xdotool key` subprocesses for each keystroke.

**Why the switch mattered:** `xdotool` triggers GNOME's RemoteDesktop portal authorization dialog on every new subprocess when running under Wayland via XWayland. The Xlib backend, running in-process as the already-authorized app, bypasses this entirely.

---

## Class: `XlibBackend`

### Lifecycle

```python
backend = XlibBackend()
backend.connect()      # opens Display connection
# ... use backend ...
backend.disconnect()   # closes Display connection
```

`InputService` calls `connect()` on startup and `disconnect()` on shutdown. The display connection is kept open for the lifetime of the session to avoid reconnection overhead on every keystroke.

---

## Methods

### `get_window_x(win_id_str) → int | None`

Gets a window's X screen coordinate using `window.translate_coords(root, 0, 0)`. Used by `WindowManager` to determine left-to-right ordering of game windows.

**Known quirk:** On XWayland compositors, `translate_coords` may return negated values. `WindowManager.assign_windows()` handles this by looking at all window X positions as a batch and correcting for consistent negation.

### `get_window_pid(win_id_str) → int | None`

Uses the XRes extension (`res_query_client_ids` with `LocalClientPIDMask`) to get the host-namespace PID for a window. This is more reliable than `xdotool getwindowpid` for Flatpak instances because the X server always knows the real host PID of its clients, regardless of namespace sandboxing.

Returns `None` if the XRes extension is unavailable or the query fails.

### `_keycode_for(keysym_str) → int | None`

Converts an xdotool-style keysym string (e.g., `"w"`, `"Up"`, `"Return"`) to an X keycode:

1. Tries `XK.string_to_keysym(keysym_str)` — handles named keys.
2. Falls back to `ord(keysym_str)` for single-character strings.
3. Calls `display.keysym_to_keycode(ks)` to get the hardware keycode.

Returns `None` if lookup fails (key not in the X keymap).

### `_modifier_mask(modifiers) → int`

Converts a list of modifier name strings (`"shift"`, `"ctrl"`, `"alt"`) to an X modifier bitmask using:

```python
MODIFIER_MASKS = {
    "shift": X.ShiftMask,
    "ctrl":  X.ControlMask,
    "alt":   X.Mod1Mask,
}
```

### `_make_event(win, event_type, keycode, state) → KeyPress | KeyRelease`

Constructs an Xlib protocol `KeyPress` or `KeyRelease` event with:
- `time = X.CurrentTime`
- `root = display.screen().root`
- `window = target window`
- `same_screen = 1`
- `root_x/y = 0`, `event_x/y = 0` (position irrelevant for movement keys)
- `state = modifier mask`
- `detail = keycode`

### `send_keydown(win_id_str, keysym_str, state=0) → bool`

Sends a `KeyPress` event to the window. Returns `False` if the keycode lookup fails or the display is disconnected.

### `send_keyup(win_id_str, keysym_str, state=0) → bool`

Sends a `KeyRelease` event to the window.

### `send_key(win_id_str, keysym_str, modifiers=None) → bool`

Sends a complete keystroke (down + up) with optional modifiers. Used for one-shot actions like keep-alive key presses and chat key sends. Calls `display.flush()` between press and release.

### `_send(win_id_str, event_type, keysym_str, state) → bool`

Core internal method. Gets keycode, creates the window resource object, constructs the event, calls `win.send_event(propagate=True)`, flushes the display. Handles `error.BadWindow` (window closed between assignment and send) silently.

### `sync()`

Calls `display.sync()` — flushes the X event queue and waits for the server to process all pending events. Called by `InputService` at the end of a broadcast cycle to ensure all keystrokes are delivered before the next cycle.

---

## Dependencies

- `Xlib.display`, `Xlib.X`, `Xlib.XK`, `Xlib.error`
- `Xlib.protocol.event`
- `Xlib.ext.res` (XRes extension, used in `get_window_pid`)

---

## Known Issues / Technical Debt

- `get_window_x()` on XWayland can return negated values. The workaround lives in `WindowManager`, not here — makes the XlibBackend less self-contained.
- Only `Mod1Mask` is used for Alt. Some Linux setups use `Mod5Mask` or others for AltGr. Not a practical issue for the game's control keys (WASD, arrows), which don't use Alt modifiers.
- The display connection is opened once and reused. If the X display drops (e.g., display server restart), the backend will silently fail until the app is restarted — there's no reconnect logic.
