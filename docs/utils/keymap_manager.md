# utils/keymap_manager.py

## Purpose

Manages movement key sets (keymaps) for per-toon custom control schemes. Provides the translation engine used by `InputService` to convert user keypresses into the appropriate key for each background toon's game client.

---

## Constants

```python
DIRECTIONS = ["up", "left", "down", "right", "jump", "book", "gags", "tasks", "map"]
MAX_SETS = 8

DEFAULT_SETS = [
    {"name": "Set 1 (WASD)", "keys": {"up": "w", "left": "a", "down": "s", "right": "d", ...}},
    {"name": "Set 2 (Arrows)", "keys": {"up": "Up", "left": "Left", "down": "Down", "right": "Right", ...}},
]
```

Two default sets ship: WASD (the standard TTR layout) and Arrows. Users can add up to 6 more.

---

## Storage

```
~/.config/toontown_multitool/keymaps.json
```

Format: list of `{"name": str, "keys": {direction: keysym_str}}` objects. Set 1 is always index 0.

---

## Class: `KeymapManager`

### `_load()`

Loads from JSON. If the file doesn't exist or is empty, initializes with `DEFAULT_SETS`. On load, **backfills** any missing direction keys with defaults — this allows new directions (e.g., adding "map" in a future version) to be added without breaking existing user configs.

### `_save()`

Writes to JSON immediately. Called on every change.

### `on_change(callback)` / `_notify()`

Registers change listeners. Called when any set is added, deleted, renamed, or has a key updated. `InputService` and `KeymapTab` subscribe to stay in sync.

### Getters

```python
get_sets()                          → list[dict]  # all sets (copy)
get_set(index)                      → dict        # single set (copy)
get_set_names()                     → list[str]
num_sets()                          → int
get_set1_keys()                     → frozenset   # all keys in Set 1 (user's physical keys)
get_all_keys()                      → frozenset   # all keys across all sets
```

### Translation

```python
get_direction(key)                  → str | None  # Set-1 key → direction name
get_direction_in_set(set_i, key)    → str | None  # arbitrary set key → direction
get_key_for_direction(set_i, dir)   → str | None  # direction → key in target set
translate(pressed_key, target_set_index) → str | None
```

`translate(pressed_key, target_set_index)` is the core operation used by `InputService`:
1. `get_direction(pressed_key)` — what direction did the user's physical key represent?
2. `get_key_for_direction(target_set_index, direction)` — what key does the target toon use for that direction?
3. Returns the target key, or `None` if either lookup fails

### Mutations

```python
add_set(name, keys)            # adds at end, max MAX_SETS
delete_set(index)              # index 0 (Set 1) is protected
update_set_name(index, name)
update_set_key(set_i, dir, key)
next_default_name(exclude_i)   # returns "Set N" for next available N
```

All mutations save immediately and call `_notify()`.

### Thread Safety

All access to `_sets` is protected by `threading.Lock`. Necessary because `InputService` reads from a background thread while `KeymapTab` writes from the main thread.

---

## Dependencies

- `os`, `json`, `threading`

---

## Known Issues / Technical Debt

- The 9-direction list (`DIRECTIONS`) is hardcoded in both this module and `keymap_tab.py`. Adding a new direction requires updating both places.
- `translate()` only works for Set-1 keys. If a user presses a key that's in Set 2 but not Set 1, translation returns None (silently dropped). This is correct behavior (only Set-1 physical keys trigger input), but the constraint isn't documented at the call site.
