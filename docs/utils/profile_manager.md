# utils/profile_manager.py

## Purpose

Manages 5 named user profiles. Each profile stores which of the 4 toon slots are enabled and what movement mode each slot uses. Profiles allow users to quickly switch between different multiboxing configurations (e.g., "Solo", "Duo", "All 4").

---

## Constants

```python
NUM_PROFILES = 5
DEFAULT_NAMES = ["Profile 1", "Profile 2", ..., "Profile 5"]
```

---

## Storage

```
~/.config/toontown_multitool/profiles.json
```

Format: JSON array of 5 objects, each with `name`, `enabled_toons` (bool list), and `movement_modes` (str list).

Config directory is created with `chmod 0o700` (owner-only access).

---

## Class: `ProfileManager`

### `_load()`

Reads `profiles.json`. Handles three cases:

1. **File missing or unreadable** — initializes all 5 profiles with defaults.
2. **Fewer than 5 profiles in file** — appends default entries until 5 exist. Allows adding new slots in future versions without breaking existing configs.
3. **More than 5 profiles** — truncates to first 5.

After ensuring 5 entries, **back-fills** any missing keys per profile (`name`, `enabled_toons`, `movement_modes`). Same forward-compatibility pattern used in `KeymapManager._load()`.

### `_save()`

Writes to JSON with 2-space indentation. Calls `f.flush()` before close, but **not `os.fsync()`** (unlike `SettingsManager`). Given profiles are user-editable presets, the slight durability reduction is acceptable.

---

## Read API

```python
get_profile(index)      → ToonProfile   # full copy of the profile at index
get_name(index)         → str           # just the display name
get_all_names()         → list[str]     # all 5 names, for populating dropdowns
```

`get_profile()` returns a `ToonProfile.from_dict()` copy — callers can't mutate the internal list by accident.

---

## Write API

```python
save_profile(index, enabled_toons, movement_modes)   # update slot data, preserve name
rename_profile(index, name)                          # update name only
move_up(index)                                       # swap with profile above
move_down(index)                                     # swap with profile below
```

### `save_profile()`

Updates data but **preserves the profile name**. This is intentional — renaming and saving data are separate UI actions in the `MultitoonTab`. Callers cannot accidentally reset the name by saving slot state.

### `rename_profile()`

Strips whitespace from the new name. Falls back to the default "Profile N" if the stripped name is empty (prevents blank-name profiles).

### `move_up()` / `move_down()`

Swap adjacent profiles in the list. Used for re-ordering profiles in the UI. No range check needed beyond the guard: `move_up` requires `index >= 1`, `move_down` requires `index <= NUM_PROFILES - 2`.

---

## Dependencies

- `os`, `json`
- `utils/models.py` — `ToonProfile`

---

## Known Issues / Technical Debt

- No change-listener/callback system (unlike `KeymapManager` and `SettingsManager`). Components that care about profile changes must either poll or be notified through `HotkeyManager`'s `profile_load_requested` signal.
- `movement_modes` is stored but unused at runtime — see `models.py` tech debt note.
- Config directory `chmod 0o700` is set in `__init__`, which means every app startup re-asserts the permission. This is harmless but technically redundant after first run.
