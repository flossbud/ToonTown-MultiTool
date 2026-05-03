# services/input_service.py

## Purpose

Core input broadcasting engine. Reads key events from a queue (filled by `HotkeyManager`), decides which background game windows should receive each event, translates keys through per-toon keymap sets, and sends synthetic key events via the configured backend (Xlib or Win32). At 695 lines, this is the most complex file in the codebase.

---

## Major Changes from v1.5

- **Keymap translation**: Instead of fixed WASD/ARROWS modes, keys are translated between arbitrary keymap sets (Set 1 = user's physical keys, Set N = target toon's expected keys)
- **Phantom chat detection**: Detects stealth whisper typing (3+ chars without chat open) and mutes further broadcast
- **Chat idle timeout**: Auto-closes background toon chat boxes after 15s inactivity
- **WindowManager integration**: No longer owns `ActiveWindowCache` internally — delegates to `WindowManager`
- **`global_chat_active` tracking**: Tracks whether the focused window's chat is open (for logging/phantom logic)
- **Pre-built `_KEYSYM_LOOKUP` dict**: O(1) keysym resolution instead of two-step lookup chain

---

## Signals

```python
log_signal: Signal(str)          # general logging
input_log: Signal(str)           # input-specific logging
window_ids_updated: Signal(list) # window list changed (forwarded from WindowManager)
chat_state_changed: Signal(bool) # True = chat opened, False = chat closed (focused window)
```

---

## Class-Level Constants

```python
WASD_KEYS      = frozenset({'w','a','s','d'})
MOVEMENT_KEYS  = WASD_KEYS | frozenset({'Up','Down','Left','Right','space'})
ARROW_KEYS     = frozenset({'Up','Down','Left','Right'})
MODIFIER_KEYS  = frozenset({'Shift_L','Shift_R','Control_L','Control_R','Alt_L','Alt_R'})

BACKSPACE_REPEAT_DELAY    = 0.4
BACKSPACE_REPEAT_INTERVAL = 0.05
CHAT_IDLE_TIMEOUT         = 15.0  # seconds before auto-closing background chat

_KEYSYM_LOOKUP: dict  # pre-built from NAMED_KEYSYMS + CHAR_TO_PHYSICAL_KEYSYM
```

`_KEYSYM_LOOKUP` is built once at class definition time by merging `NAMED_KEYSYMS` and `CHAR_TO_PHYSICAL_KEYSYM`, enabling O(1) `_resolve_keysym()` instead of the two-lookup chain in v1.5.

---

## State Tracking

| Attribute | Type | Description |
|-----------|------|-------------|
| `keys_held` | `set` | Movement/special keys currently held |
| `modifiers_held` | `set` | Modifier keys held (Shift, Ctrl, Alt) |
| `bg_typing_held` | `set` | Chat/typing keys held (separate from movement) |
| `chat_active` | `set[int]` | Toon indices with chat box open |
| `global_chat_active` | `bool` | Whether the focused window's chat is open |
| `_phantom_active` | `bool` | Stealth whisper mode engaged |
| `_phantom_char_count` | `int` | Count of printable chars since phantom trigger |
| `_last_typing_time` | `float` | Timestamp of last chat key (for idle timeout) |

---

## `__init__`

Takes dependencies via injection:
- `window_manager` — used for active window queries (replaces `ActiveWindowCache`)
- `get_enabled_toons` — callable → `list[bool]`
- `get_movement_modes` — callable → `list[str]` (legacy WASD/ARROWS or set names)
- `get_event_queue_func` — callable → `queue.Queue`
- `get_chat_enabled` — callable → `list[bool]`
- `settings_manager` — for backend preference
- `keymap_manager` — optional; if None, falls back to WASD/ARROWS legacy logic

---

## `start()` / `stop()` / `shutdown()`

Same pattern as v1.5. `start()` applies the backend setting, starts the event loop thread. `stop()` sets `running=False` and calls `release_all_keys()`. `shutdown()` also disconnects Xlib.

---

## `run()` — Main Event Loop

Runs on a daemon thread at ~200Hz (`time.sleep(0.005)`).

### Guard: `should_send_input()`

Delegates to `window_manager.should_capture_input()` — returns True if a TTR/CC window or the MultiTool is focused. On False: flushes queue, releases held keys, clears chat state.

### Event Processing

**Keydown routing:**

| Key type | Routing |
|----------|---------|
| Modifier (Shift/Ctrl/Alt) | `_send_modifier_to_bg()` |
| Movement key (WASD/arrows/space) | `_send_movement_key_km()` |
| BackSpace | `_send_movement_key_km()` + hold-repeat timer |
| Return | Toggle `chat_active` for ARROWS-mode toons; `_send_typing_to_bg()` |
| Escape | Close `chat_active` for ARROWS-mode toons; `_send_typing_to_bg()` |
| Other (printable chars) | `_send_typing_to_bg()` |

**Phantom detection** (for printable chars):
- If chat is NOT open and 3 printable chars have been typed → activate `_phantom_active`
- While phantom active, typing is not forwarded to background toons
- Return or Escape resets phantom mode

**Chat idle timeout**:
- After each typing key, `_last_typing_time` is updated
- Each loop iteration checks: if chat is open and `now - _last_typing_time > CHAT_IDLE_TIMEOUT` → `_timeout_reset_chat()` sends Escape to background toons

---

## `_movement_keys()` → frozenset

Returns all keys across all keymap sets — used to check if a pressed key is a movement key in any set, not just Set 1.

---

## `_get_assignments(enabled)` → list[int | None]

For each enabled toon slot, returns the keymap set index that toon should use. Returns the set index from the movement mode string (e.g., "Set 2" → index 1), or `None` if the toon is disabled.

---

## `_send_movement_key_km(action, key, enabled, assignments)`

The keymap-aware movement key sender:
1. Find which direction `key` represents in Set 1 (via `keymap_manager.get_direction()`)
2. For each enabled toon with an assignment:
   - Get the target key for that direction in the toon's assigned set (via `keymap_manager.get_key_for_direction()`)
   - Resolve to keysym and send
3. Falls back to legacy WASD/ARROWS logic when `keymap_manager` is None

Active (focused) window is skipped — the real keyboard handles it.

---

## `_send_modifier_to_bg(action, key, enabled, assignments)`

Sends modifier key events to all enabled background windows. Modifiers broadcast regardless of movement mode — needed for Shift+key combos during chat.

**Shift as jump key edge case**: If Shift is mapped as the "jump" direction in a keymap set, the input service treats it as a modifier for typing purposes when chat is active, not as a movement key to translate. This prevents Shift from being sent as two different things simultaneously.

---

## `_send_typing_to_bg(key, enabled, assignments, movement_keys)`

Sends chat/typing keys to background windows with per-toon filtering:
- If phantom active: skip
- ARROWS-mode toons: only receive WASD chars if `chat_active` (chat box open for that toon)
- WASD-mode toons: skip arrow keys
- Return/Escape: only if chat is allowed for that toon
- Active window: always skipped
- Active modifiers included in send (for Shift+letter, Ctrl+letter, etc.)

---

## `_resolve_keysym(key)` → str | None

O(1) lookup in the pre-built `_KEYSYM_LOOKUP` dict. Returns the X11 keysym string, or `None` if unrecognized.

---

## `_set_chat_active(active)` / `_phantom_reset()`

`_set_chat_active` updates `global_chat_active` and emits `chat_state_changed` for UI updates. `_phantom_reset` clears `_phantom_active` and `_phantom_char_count`.

---

## `_timeout_reset_chat(enabled, assignments)`

Called when chat idle timeout fires. Sends Escape to all background toons with open chat, and clears `chat_active` for those toons.

---

## `send_keep_alive_key(key)` / `send_keep_alive_to_window(win_id, key, modifiers)`

Send keep-alive keypresses. `send_keep_alive_key` sends to all known windows. `send_keep_alive_to_window` sends to a specific window with optional modifiers. Both check keysym resolution and use the configured backend.

---

## `_send_via_backend(action, win_id, keysym, modifiers=None)`

Routes to XlibBackend (Linux) or Win32Backend (Windows) based on `_xlib` reference:
- Xlib: `send_keydown/send_keyup/send_key`
- xdotool fallback: `xdotool keydown/keyup/key --window`
- Win32: `send_keydown/send_keyup/send_key`

---

## `release_all_keys()`

Sends keyup for all held movement and modifier keys to all background windows. Called on stop to prevent stuck keys.

---

## Threading

- `run()` on daemon thread started by `start()`
- Key event queue is the thread-safe handoff from `HotkeyManager` (pynput thread)
- `window_ids_updated` signal: Qt routes from service thread to main thread automatically
- `chat_state_changed` signal: same routing

---

## Known Issues / Technical Debt

- `run()` at ~250 lines is still long. The keydown dispatch is the main complexity driver — a dispatcher table would help.
- The phantom detection char count (3) is hardcoded.
- Chat idle timeout (15s) is hardcoded.
- Legacy WASD/ARROWS fallback branches add dual-path complexity that should be removed once all users are on v2 keymap sets.
