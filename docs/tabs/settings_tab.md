# tabs/settings_tab.py

## Purpose

Application settings and customization UI with iOS-style controls (toggle switch and segmented control). Settings cover theme, input backend, Companion App support, debug log visibility, and credential management.

---

## Classes

### `IOSToggle` (QWidget)

An animated iOS-style toggle switch. Renders a rounded track and a circular thumb that slides between on/off positions via `QVariantAnimation`.

#### Signals
```python
toggled: Signal(bool)
```

#### `isChecked()` / `setChecked(val, animate=True)`

`setChecked` with `animate=True` triggers the slide animation. `animate=False` snaps immediately (used on init to avoid animation on load).

#### `set_theme_colors(off_color)`

Sets the track color when off (typically a muted gray). On color is always `accent_green`.

#### `paintEvent(e)`

Draws:
1. Rounded rect track (off color or green based on state)
2. White circle thumb at position `_anim_pos` (0.0 = left/off, 1.0 = right/on)

Thumb position is interpolated linearly from `_anim_pos`.

#### `mousePressEvent(e)`

Toggles state and emits `toggled`. Starts the animation.

---

### `IOSSegmentedControl` (QWidget)

An animated segmented control (2 or 3 segments). Renders a track with a sliding pill that highlights the selected segment.

#### Signals
```python
index_changed: Signal(int)
```

#### `setCurrentIndex(idx)` / `currentIndex()`

`setCurrentIndex` snaps without animation (for init). Selection changes via click animate the pill position.

#### `set_theme_colors(track_color, pill_color, active_text, inactive_text)`

Configures colors for the track background, selected pill, active label text, and inactive label text.

#### `paintEvent(e)`

Draws:
1. Rounded rect background (track)
2. Rounded rect pill at animated position (interpolated between segment centers)
3. Text labels for each segment, colored by active/inactive state

Segment width = total width / num_segments.

**Used by**: `DebugTab` (log category selector) and `SettingsTab` itself.

---

### `SettingsTab` (QWidget)

#### Signals
```python
debug_visibility_changed: Signal(bool)
theme_changed: Signal()
input_backend_changed: Signal()
clear_credentials_requested: Signal()
```

#### Settings Sections

**General:**
- Hints toggle (IOSToggle) — enables/disables tooltip hints app-wide
- Show Logs toggle (IOSToggle) — adds/removes debug tab from sidebar

**Theme:**
- Segmented control: System / Light / Dark

**Input:**
- Input backend segmented: Xlib / xdotool (Linux) or disabled (Windows, Win32 only)
- GNOME Wayland warning shown inline if xdotool selected on GNOME Wayland

**Companion App:**
- IOSToggle: Enable/disable TTR local API name fetching

**Account Management:**
- "Clear All Saved Credentials" button → emits `clear_credentials_requested`
- Keyring backend status display (from `CredentialsManager.format_backend_diagnostics()`)

#### `_is_gnome_wayland()` → bool

Same check as v1.5: `XDG_SESSION_TYPE == "wayland"` AND `"GNOME" in XDG_CURRENT_DESKTOP`.

#### `refresh_theme()`

Applies theme colors to all section labels, toggles, and segmented controls. Calls `set_theme_colors()` on each `IOSToggle` and `IOSSegmentedControl` to update their painted appearance.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/theme_manager.py` | Colors, `apply_theme`, `resolve_theme` |
| `utils/credentials_manager.py` | Backend diagnostics display |

---

## Key Changes from v1.5

- Checkboxes and QComboBoxes replaced with `IOSToggle` and `IOSSegmentedControl` for visual consistency
- Advanced section collapse/expand animation replaced by always-visible layout (simpler)
- "Clear All Credentials" added (new in v2 — credentials didn't exist in v1.5)
- Keyring backend status diagnostic display added
- `IOSSegmentedControl` exported and reused by `DebugTab`
