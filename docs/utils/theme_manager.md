# utils/theme_manager.py

## Purpose

Central theming and icon generation module. Provides:
- **`get_theme_colors(is_dark)`** — complete semantic color token dict for every UI component
- **Programmatic Qt icon generators** — all icons drawn with `QPainter`, no image files needed
- **`SmoothProgressBar`** — custom painted QWidget for laff/bean progress display
- **`DARK_THEME` / `LIGHT_THEME`** — global Qt stylesheet strings
- **`resolve_theme()` / `apply_theme()`** — theme selection and application
- **`SET_COLORS`** — fixed movement set identity colors
- **Helper functions** — `apply_card_shadow()`, `make_section_label()`, `get_set_color()`

---

## Icon Generators

All icons are programmatic — drawn at runtime using Qt primitives. This avoids shipping image assets and allows icons to scale to any size cleanly.

### Navigation Icons

| Function | Used in |
|----------|---------|
| `make_nav_gamepad(size, color)` | Multitoon sidebar button |
| `make_nav_power(size, color)` | Launch sidebar button |
| `make_nav_bookmark(size, color)` | Presets/Profiles sidebar button |
| `make_nav_gear(size, color)` | Settings sidebar button |
| `make_nav_keyboard(size, color)` | Keymap sidebar button |
| `make_nav_terminal(size, color)` | Logs/Debug sidebar button |

`make_nav_rocket` is an alias for `make_nav_power` (kept for import compatibility).

### Inline Icons

| Function | Description |
|----------|-------------|
| `make_chat_icon(size)` | Chat bubble with tail and three dots — used in chat broadcast UI |
| `make_refresh_icon(size)` | Circular arrow — used on manual refresh buttons |
| `make_mouse_icon(size)` | Computer mouse — used in input backend display |
| `make_heart_icon(size, color)` | Bezier-curve heart — used for laff display |
| `make_jellybean_icon(size, color)` | Pill-shaped bean with highlight — used for bean display |
| `make_trash_icon(size, color)` | Trash can with lid, handle, body, and vertical lines |
| `make_hint_icon(size, color, active)` | `?` in circle — hint toggle button |
| `make_edit_icon(size, color)` | Pencil icon — edit profile name button |
| `make_info_icon(size, color)` | `i` in circle — about/credits button |

### `_draw_nav_icon(size, color, draw_func) → QIcon`

Private helper that sets up a transparent pixmap + painter, calls `draw_func(painter, size, color)`, and returns a `QIcon`. Most nav icon generators delegate to this.

---

## `SmoothProgressBar` (QWidget)

A custom-painted progress bar. Used in `MultitoonTab` for laff and bean fill levels.

```python
bar = SmoothProgressBar()
bar.set_progress(0.75)           # 0.0–1.0
bar.set_fill_color("#4fc95c")    # hex string
bar.set_bg_color("#141414")
```

### `paintEvent()`

- Draws a rounded pill (full width) as the track background.
- Draws a shorter pill as the fill, clamped to a minimum width of `height` so the fill never collapses to a sharp edge.
- Uses `QPainter.Antialiasing` for smooth edges.
- Fixed height of 7px. Width is flexible.

---

## `SET_COLORS`

8-element list of `(bg_hex, text_hex)` tuples, one per movement key set (index 0–7).

```python
SET_COLORS = [
    ("#4A8FE7", "#ffffff"),   # 1 — Blue
    ("#E05252", "#ffffff"),   # 2 — Red
    ("#DAA520", "#1a1a1a"),   # 3 — Yellow/Gold
    ...
]
```

Colors are **fixed across light and dark themes** — they're identity colors for key sets, not UI chrome. `get_set_color(index)` returns the pair for a given 0-based index, with a grey fallback for out-of-range indices.

---

## `get_theme_colors(is_dark) → dict`

Returns a flat dict of ~65 semantic color tokens. Both light and dark variants define the same set of keys, so callers can use `c["bg_card"]` without checking the theme themselves.

### Color categories

- **Backgrounds**: `bg_app`, `bg_card`, `bg_card_inner`, `bg_input`, `bg_input_dark`, `bg_status`
- **Sidebar**: `sidebar_bg`, `sidebar_btn`, `sidebar_btn_sel`, `sidebar_text`, `sidebar_text_sel`, `sidebar_border`
- **Header**: `header_bg`, `header_text`, `header_sub`, `header_accent`
- **Borders**: `border_card`, `border_input`, `border_muted`, `border_light`
- **Text**: `text_primary`, `text_secondary`, `text_muted`, `text_disabled`
- **Accent greens** (launch success, active state): `accent_green`, `accent_green_border`, `accent_green_hover`, etc.
- **Accent blues** (buttons, links): `accent_blue`, `accent_blue_btn`, `accent_blue_btn_border`, etc.
- **Accent reds** (delete, danger): `accent_red`, `accent_red_border`, `accent_red_hover`, etc.
- **Accent orange** (keep-alive active): `accent_orange`, `accent_orange_border`, `accent_orange_hover`
- **Status strips**: `status_success_*`, `status_warning_*`, `status_idle_*`
- **Buttons**: `btn_bg`, `btn_border`, `btn_hover`, `btn_disabled`, `btn_text`
- **Dropdowns**: `dropdown_bg`, `dropdown_text`, `dropdown_border`, `dropdown_list_bg`, `dropdown_sel_*`
- **Slot badges**: `slot_1`–`slot_4`, `slot_dim`
- **Toon cards**: `card_toon_bg`, `card_toon_border`, `card_toon_active_bg`
- **Segment bar**: `segment_off`, `segment_found`, `segment_active`

---

## Global Stylesheets

`DARK_THEME` and `LIGHT_THEME` are multiline stylesheet strings applied with `app.setStyleSheet()`. They style base Qt widgets (`QWidget`, `QPushButton`, `QComboBox`, etc.) with appropriate colors, border-radius, padding, and font-family.

Font stack: `'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif` — covers modern Linux and Windows.

---

## `resolve_theme(settings_manager) → str`

Returns `"dark"` or `"light"`:
1. If the user's setting is `"light"` or `"dark"`, returns that directly.
2. If `"system"`, reads `QPalette.Base` color value — if `< 128`, the system is using a dark theme.

### `apply_theme(app, theme)`

Sets `app.setStyleSheet()` from `DARK_THEME` or `LIGHT_THEME`. Passes empty string for any other value (resets to system default).

---

## Helper Functions

### `apply_card_shadow(widget, is_dark, blur=18, offset_y=3)`

Adds a `QGraphicsDropShadowEffect` to a widget. Dark mode uses a heavier shadow (`rgba(0,0,0,90)`); light mode is subtler (`rgba(0,0,0,40)`).

### `make_section_label(text, c) → QLabel`

Returns a styled section header label — uppercase, small font (10px), muted color, letter-spacing for a "label" feel.

---

## Dependencies

- `PySide6.QtGui`, `PySide6.QtWidgets`, `PySide6.QtCore`
- `math` — for gear teeth and refresh arrow tip calculations

---

## Known Issues / Technical Debt

- `get_theme_colors()` returns a copy of a large dict on every call. Some tabs call this in `paintEvent()` or resize events, creating unnecessary allocations. Could be cached and invalidated on theme change.
- The dark/light stylesheets only cover base widgets. Component-specific styling (cards, slot badges, etc.) is done inline per-component, not via stylesheet. This is intentional (more control) but means theme changes require all components to call `refresh_theme()` explicitly.
- `make_nav_rocket` alias for `make_nav_power` exists only to avoid breaking old import references. There's no longer a rocket icon in the UI.
