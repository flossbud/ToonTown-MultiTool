# tabs/credits_tab.py

## Purpose

A simple about/credits display tab. Shows app name, description, and creator byline. New in v2.

---

## Class: `CreditsTab` (QWidget)

### `build_ui()`

Centered card containing:
- App name label (large, bold)
- Description text (what the app does)
- Creator byline ("Made by flossbud")

All text is centered, no interactive elements.

### `refresh_theme()`

Updates card background, border, and text colors via `get_theme_colors()`.

### `_on_setting_changed(key, value)`

Connected to `SettingsManager.on_change()`. Only acts on `key == "theme"` to trigger `refresh_theme()`.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/theme_manager.py` | Theme colors |
| `utils/settings_manager.py` | Theme change notifications |
