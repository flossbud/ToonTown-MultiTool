# tabs/launch_tab.py

## Purpose

Account management and game launching UI for both TTR and CC. Displays account slots with per-slot login status chips, handles add/edit/delete/reorder of accounts, shows a collapsible edit panel, and drives the login→launch flow. This is the most UI-complex tab in the app.

---

## Constants

```python
STATUS_COLORS: dict   # LoginState → hex color
STATUS_LABELS: dict   # LoginState → human-readable string
SLOT_COLORS: list     # per-slot badge colors (separate lists for TTR and CC)
GAME_LABELS: dict     # "ttr" → "TOONTOWN REWRITTEN", "cc" → "CORPORATE CLASH"
GAME_ACCENT: dict     # "ttr" → color, "cc" → color
MAX_PER_GAME = 8      # hard ceiling on accounts per game
```

---

## Classes

### `AnimatedEditPanel` (QFrame)

A collapsible panel for the account edit form. Animates `maximumHeight` between 0 (collapsed) and `sizeHint().height()` (expanded) over 220ms.

#### `expand()` / `collapse()`

Standard animate-then-show/animate-then-hide pattern. On collapse, hides the widget after animation completes via `finished` signal.

---

### `SlotBadge` (QWidget)

A colored circle (40×40) with a white slot number painted on it. Drawn via `paintEvent` using `QPainter` with `Antialiasing`. Color comes from `SLOT_COLORS` based on game type and slot index.

---

### `StatusChip` (QLabel)

A pill-shaped status indicator. Shows login state text with rounded background color from `STATUS_COLORS`. Hidden when state is IDLE. Updated by the login worker's `state_changed` signal.

---

### `KeyringProbeWorker` (QObject)

Background worker that probes keyring availability on startup. Emits a signal when complete. Used to trigger the `KeyringPendingBanner` display/hide.

---

### `KeyringPendingBanner` (QFrame)

Shows a "⏳ Checking credential storage…" message while the keyring probe runs. Automatically hidden when `KeyringProbeWorker` completes.

---

### `LaunchTab` (QWidget)

The main account management tab.

#### `build_ui()`

Builds two sections (TTR and CC) each with:
- Section header (game label + accent color)
- Grid of account slot rows
- "Add account" button

Below that: the `AnimatedEditPanel` for editing.

Each account slot row contains:
- `SlotBadge` (slot number + color)
- Account label and username
- `StatusChip`
- Launch button (starts login flow)
- Edit / Delete buttons

#### Account CRUD

- **Add**: Opens edit panel with blank fields, saves to `CredentialsManager` on confirm
- **Edit**: Populates edit panel from account, updates on confirm
- **Delete**: Removes from `CredentialsManager`, rebuilds slot rows
- **Reorder**: Drag or arrow buttons move accounts up/down via `CredentialsManager.reorder()`

#### Login Flow (per slot)

1. User clicks Launch button for an account
2. `TTRLoginWorker` or `CCLoginWorker` created for that slot
3. Worker signals wired to slot-specific UI:
   - `state_changed` → update `StatusChip`
   - `need_2fa` → show 2FA input dialog
   - `queue_update` → update status with position/ETA
   - `login_success` → trigger launcher
   - `login_failed` → show error in StatusChip
4. On `login_success(gameserver, cookie)`:
   - `TTRLauncher.launch(gameserver, cookie, engine_dir)` or `CCLauncher.launch(...)`
   - Worker transitions to LAUNCHING state

#### Keyring Probe

On tab creation, `KeyringProbeWorker` runs in background. While pending:
- `KeyringPendingBanner` is shown
- Add/Launch buttons are disabled (can't safely read keyring)

On completion:
- Banner hides
- If keyring available: normal operation
- If unavailable: show warning, in-memory fallback active

#### `on_clear_credentials_requested()`

Connected from `SettingsTab` / `main.py`. Calls `CredentialsManager.clear_all()`, cancels any active login workers, rebuilds the slot UI.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `services/ttr_login_service.py` | `TTRLoginWorker`, `LoginState` |
| `services/ttr_launcher.py` | `TTRLauncher` |
| `services/cc_login_service.py` | `CCLoginWorker` |
| `services/cc_launcher.py` | `CCLauncher` |
| `utils/credentials_manager.py` | Account storage |
| `utils/theme_manager.py` | Colors |
| `tabs/multitoon_tab.py` | `PulsingDot` (reused for per-slot visual) |

---

## Known Issues / Technical Debt

- Importing `PulsingDot` from `multitoon_tab.py` creates a cross-tab dependency. `PulsingDot` should be in a shared widgets module.
- The edit panel is a single shared widget — only one account can be edited at a time. A race condition exists if the user starts editing one account, then quickly tries another.
- Login worker references are stored in a dict keyed by account index — if accounts are reordered while a login is in progress, the mapping can become stale.
