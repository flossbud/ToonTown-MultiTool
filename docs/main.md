# main.py

## Purpose

Application entry point and primary `QMainWindow`. Builds the sidebar navigation UI, initializes all managers and services, wires cross-component signals, and manages top-level app lifecycle. In v2, `main.py` is significantly more of a pure shell than v1.5 — hotkey logic is in `HotkeyManager`, service start/stop is in `WindowManager`/`InputService`, and presets became `ProfileManager`.

`APP_VERSION = "2.0"`

---

## Classes

### `NoFocusProxyStyle` (QProxyStyle)

Suppresses Qt's dotted focus rectangle on focused widgets. Applied globally at startup via `app.setStyle(NoFocusProxyStyle(...))`. Purely cosmetic.

---

### `AnimatedNavButton` (QPushButton)

A sidebar navigation button with a smooth icon-size hover animation. On `enterEvent`, expands icon from 28px to 32px over 200ms with `OutCubic` easing. On `leaveEvent`, shrinks back. The animation targets the button's `iconSize` property via `QPropertyAnimation`.

Used for all primary navigation buttons in the sidebar (Multitoon, Launch, Keymap, Settings, Invasions).

---

### `MultiToonTool` (QMainWindow)

The main window. Owns all managers, all tab instances, and the top-level layout.

#### `__init__`

Initialization order matters:
1. Create `SettingsManager`, `KeymapManager`, `ProfileManager`
2. Create `DebugTab` (needed as logger before other tabs)
3. Create `WindowManager`, `HotkeyManager`
4. Create all tabs (passing managers/services as needed)
5. Build header and sidebar
6. Wire signals
7. Apply theme
8. Defer `_capture_multitool_window_id()` via `QTimer.singleShot(0, ...)` — the window isn't registered with X11 until after `show()`, so the capture must happen after the event loop starts

#### Layout Structure

```
QMainWindow
└── central QWidget (HBox)
    ├── sidebar (QWidget, VBox)   ← nav buttons
    └── content_area (QWidget, VBox)
        ├── header (QWidget)     ← accent stripe + title + version
        └── QStackedWidget       ← tab pages
```

#### `_build_header()`

Creates the top header bar:
- A 4px colored accent stripe at the top (uses `accent_green` color)
- Title label "ToonTown MultiTool" with animation (`_animate_launch`)
- Version label "v2.0"
- Byline "by flossbud"

The title label starts at `maximumWidth=0` and expands to 300px over 800ms via `QPropertyAnimation` — a startup reveal animation.

#### `_build_sidebar()`

Builds the left nav column:
- `AnimatedNavButton` for each primary tab (with icon + tooltip)
- Spacer to push secondary buttons to bottom
- Small icon-only buttons for Logs and Credits at the bottom
- Hint toggle button (question mark icon)

All nav buttons call `nav_select(index)` on click.

#### `nav_select(index)`

Switches `QStackedWidget` to the target page with a fade-in animation (`QGraphicsOpacityEffect` on the stacked widget, animated 0→1 over 180ms). Updates sidebar button styles and icons to show selection state.

#### `_apply_nav_icons()` / `_apply_nav_styles()`

Separate methods for icon and style updates on nav buttons — called together on nav change and theme change. Icons use functions from `theme_manager` (e.g., `make_nav_gamepad`, `make_nav_power`) and change color based on selected/unselected state.

#### `_theme_colors()` / `_apply_full_theme()`

`_theme_colors()` returns the current theme's color dict. `_apply_full_theme()` applies styles to the header, sidebar, and content area. Called at init and whenever `on_theme_changed()` fires.

#### `_toggle_hints()` / `_update_hint_icon()`

Hint tooltips are globally suppressed via `eventFilter` unless enabled. `_toggle_hints()` flips the setting and saves it. `_update_hint_icon()` updates the hint button's icon color to reflect state. When disabled, `eventFilter` intercepts `QEvent.ToolTip` events and swallows them (except on the hint button itself).

#### `eventFilter(obj, event)`

Installed on `QApplication` to block tooltip events application-wide when hints are disabled. The exception: the hint button always shows its tooltip.

#### `on_theme_changed()`

Connected to `SettingsTab`'s theme change signal. Re-applies full theme and re-calls `refresh_theme()` on each tab.

#### `on_input_backend_changed()`

If the input service is running, stops and restarts it to pick up the backend change.

#### `toggle_debug_tab_visibility(show)`

Shows or hides the Logs sidebar button and, if hiding, switches away from the Logs tab if it's currently active.

#### `on_clear_credentials_requested()`

Connected from `SettingsTab`. Calls `CredentialsManager.clear_all()` and resets any in-flight login state.

#### `load_profile_slot(index)`

Connected to `HotkeyManager.profile_load_requested`. Delegates to `MultitoonTab` to load the profile at the given index (0-based). Saves `active_profile` in settings.

#### `_capture_multitool_window_id()`

Uses `xdotool search --name "ToonTown MultiTool"` to find the app's own X11 window ID and stores it in `SettingsManager`. This allows `WindowManager` and `InputService` to recognize when the MultiTool itself is focused (input should still be captured/broadcast in that case). The call is deferred with `QTimer.singleShot(0)` so the window is fully realized before the search.

#### `closeEvent(event)`

Cleanup on app exit:
1. Stop `HotkeyManager`
2. Stop `InputService` (releases held keys)
3. Stop `WindowManager`
4. Persist keep-alive key if set

#### `log(message)`

Appends to `DebugTab` with `append_log()`. Used internally and passed to services/tabs as a logging callback.

---

## Entry Point (`__main__`)

1. Sets `QT_QPA_PLATFORM=xcb` as env default (top of file) — forces X11 mode on Wayland for the app itself
2. Creates `QApplication` with `NoFocusProxyStyle`
3. Loads and registers Noto Color Emoji font as fallback
4. Applies initial theme via `apply_theme()`
5. Creates and shows `MultiToonTool`

---

## Dependencies

| Module | Used for |
|--------|----------|
| All tab modules | Tab widget instances |
| `utils/settings_manager.py` | App settings |
| `utils/theme_manager.py` | Theme application, icon generation |
| `utils/keymap_manager.py` | Passed to tabs needing keymap access |
| `utils/profile_manager.py` | Passed to multitoon tab |
| `utils/game_registry.py` | Initialized at startup |
| `services/window_manager.py` | Window detection service |
| `services/hotkey_manager.py` | Global hotkey listener |

---

## Key Changes from v1.5

- Hotkey logic extracted to `HotkeyManager` — `main.py` no longer owns the pynput listener
- Flat tab bar replaced with animated sidebar
- Preset save/load replaced by `ProfileManager` + `HotkeyManager.profile_load_requested` signal
- Window ID capture deferred properly (was racy in v1.5)
- `_enabled_style()` / `_disabled_style()` inline style methods gone — theme-aware styling lives in tabs
- `save_preset()` / `load_preset()` orchestration gone — handled by `MultitoonTab` + `ProfileManager`
