# tabs/keymap_tab.py

## Purpose

UI for creating, editing, and deleting custom movement key sets (keymaps). Each set defines 9 directions (up, left, down, right, jump, book, gags, tasks, map). Set 1 is always the user's physical keys. Additional sets (2–8) define what each background toon's game client expects to receive.

---

## Constants

```python
DIRECTIONS = ["up", "left", "down", "right", "jump", "book", "gags", "tasks", "map"]
DIRECTION_LABELS = ["Up", "Left", "Down", "Right", "Jump", "Open Book", "Open Gags", "Open Tasks", "Open Map"]
DISPLAY_NAMES: dict    # keysym string → friendly name ("w" → "W", "Up" → "Up Arrow", etc.)
SPECIAL_KEYS: dict     # Qt.Key_* → keysym string
_NUMPAD_KEYS: set      # Qt numpad key codes
```

---

## Classes

### `MovementKeyField` (QLineEdit)

A read-only key capture input field. Clicking activates "awaiting" mode ("Press a key…"); the next keypress is captured as the binding.

#### Signals
```python
key_captured: Signal(str)  # emitted with the captured keysym string
```

#### `mousePressEvent(e)`

Sets `_awaiting = True` and updates display.

#### `keyPressEvent(e)`

When awaiting:
1. Check `_NUMPAD_KEYS` — if numpad key and Num Lock active, return numpad keysym
2. Check `SPECIAL_KEYS` — maps Qt key codes to keysym strings
3. On Windows: call `_side_aware_modifier_key(event)` for left/right modifier distinction
4. Fall back to `e.text()` for printable characters
5. Set key, emit `key_captured`, clear focus

#### `_side_aware_modifier_key(event)` (Windows only)

Uses `ctypes.windll.user32.GetAsyncKeyState(vk)` to determine which side of the keyboard a modifier was pressed on (e.g., Left Ctrl vs Right Ctrl). Returns `"Control_L"` / `"Control_R"` etc. Needed because Qt's `key()` returns the same `Qt.Key_Control` regardless of which Ctrl was pressed.

#### `_vk_is_down(vk)` (Windows only)

Helper that calls `GetAsyncKeyState` and checks the high bit (key currently pressed).

---

### `KeymapTab` (QWidget)

#### `build_ui()`

Builds a layout with:
- Set selector (tab-style buttons for Set 1 through Set N)
- "Add Set" and "Delete Set" buttons
- Grid of 9 direction rows, each with a `MovementKeyField`
- Set name field (editable)

#### `_load_set(index)`

Populates all 9 direction fields from `KeymapManager.get_set(index)`. Updates the set name field. Set 1 fields are editable (they define the user's physical keys); other sets' fields define translation targets.

#### `_on_key_captured(direction, key)`

Called when a `MovementKeyField` emits `key_captured`. Validates the key isn't already assigned to another direction in this set (prevents ambiguous mappings). If valid, calls `KeymapManager.update_set_key(set_index, direction, key)`.

#### `_add_set()`

Calls `KeymapManager.add_set(name, default_keys)`. Rebuilds set selector. Switches to new set.

#### `_delete_set()`

Deletes the current set (Set 1 cannot be deleted — guarded). Rebuilds set selector.

#### `refresh_theme()`

Applies theme-aware styles to all widgets.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/keymap_manager.py` | Keymap data and operations |
| `utils/theme_manager.py` | Colors, `get_set_color()` |
| `utils/symbols.py` | Emoji fallback |

---

## Known Issues / Technical Debt

- Windows-only side-aware modifier detection works via `GetAsyncKeyState`, but this is a blocking win32 call inside a key event handler. On very slow systems this could introduce input lag.
- When a key is reassigned in Set 1, there's no automatic propagation to fix conflicts in other sets — the user must manually fix other sets if a key is reused.
