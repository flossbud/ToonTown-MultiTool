# utils/models.py

## Purpose

Defines the two core data model dataclasses used across the codebase: `AccountCredential` (credential records) and `ToonProfile` (multitoon session presets). Provides `from_dict` / `to_dict` for JSON serialization.

---

## Dataclass: `AccountCredential`

```python
@dataclass
class AccountCredential:
    id: str
    label: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    game: str = "ttr"
```

### Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | str | UUID assigned at creation. Used as keyring key. |
| `label` | str | Human-readable name shown in LaunchTab (e.g., "Jaret's Toon"). |
| `username` | str | Account login email/username. |
| `password` | str | Excluded from `repr` to prevent accidental log leakage. |
| `game` | str | `"ttr"` or `"cc"`. |

### `from_dict(data, password="")`

Constructs from a JSON dict (accounts.json row) + an optional password fetched separately from keyring. Password defaults to empty string so callers can call this without fetching from keyring when only metadata is needed.

### `to_dict()`

Serializes to JSON dict. **Excludes `password`** — passwords are never written to disk through this path. Only `id`, `label`, `username`, `game` are persisted.

---

## Dataclass: `ToonProfile`

```python
@dataclass
class ToonProfile:
    name: str = ""
    enabled_toons: List[bool] = field(default_factory=lambda: [False]*4)
    movement_modes: List[str] = field(default_factory=lambda: ["Default"]*4)
```

### Fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | str | Display name for the profile selector. |
| `enabled_toons` | list[bool] | Which of the 4 toon slots are active in this profile. |
| `movement_modes` | list[str] | Per-slot movement mode — currently `"Default"` only; reserved for future modes. |

### `from_dict(data)` / `to_dict()`

Standard JSON serialization. Used by `ProfileManager` to read/write `profiles.json`.

---

## Design Notes

- `password` uses `repr=False` to prevent it appearing in debug output, tracebacks, or log dumps.
- Both models use `default_factory` for mutable defaults (list fields) — avoids the classic Python shared-mutable-default bug.
- Neither model enforces validation (e.g., `game` is not constrained to `"ttr"|"cc"`, `enabled_toons` length isn't checked). Validation is the caller's responsibility.

---

## Dependencies

- `dataclasses`, `typing`

---

## Known Issues / Technical Debt

- `movement_modes` is vestigial — only `"Default"` is used. Was included for future per-toon keymap selection (e.g., Set 2, Set 3). Until that feature lands, the field does nothing.
- No schema versioning. If fields are added/removed, old JSON files must be back-filled by callers (`ProfileManager` does this; `CredentialsManager` doesn't need to since `AccountCredential` is populated from keyring + JSON separately).
