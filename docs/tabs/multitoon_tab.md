# tabs/multitoon_tab.py

## Purpose

The main controller tab. Displays up to 4 toon slots with per-toon status, portrait, enable/chat controls, keep-alive configuration, and movement mode assignment. In v2, significant UI polish was added: animated pulsing status dots, toon portrait images from the Rendition API, and per-toon keep-alive (moved here from the old Extras tab).

---

## Classes

### `ToonPortraitWidget` (QWidget)

Renders a toon's portrait image fetched from TTR's Rendition API, falling back to a colored circle with the slot number if no image is available.

#### Signals
```python
_image_ready: Signal(str, object)  # internal: (payload_key, image_data) for thread-safe delivery
clicked: Signal()                   # emitted when portrait is clicked
```

#### `set_colors(bg, text)` / `set_border_color(color)`

Sets the fallback circle background/text colors and optional border. Colors come from `LaunchTab`'s per-slot badge colors.

#### `set_dna(dna)`

Initiates a portrait fetch using the toon's DNA string as a cache key. Cancels any in-flight fetch via a generation token (`_fetch_token`). The fetch runs in a daemon thread.

#### `_fetch(dna, token)`

Background thread: fetches the portrait image from the Rendition API URL constructed from the DNA string. On success, decodes the PNG into a `QImage`. Emits `_image_ready(token, image)` if the token is still current (not cancelled).

#### `_on_image_ready(payload, data)`

Slot (main thread): stores the image if the token matches current. Calls `update()` to trigger repaint.

#### `paintEvent(event)`

Renders either the fetched portrait image (scaled to fit, centered) or the fallback colored circle with the slot number. Uses `QPainter` with antialiasing.

---

### `PulsingDot` (QWidget)

A 12×12 animated status indicator with a soft glow effect. States:

| State | Color | Pulse |
|-------|-------|-------|
| `"active"` | Green | Yes (breathing) |
| `"keep_alive"` | Blue | Yes |
| `"found"` | Gray (muted) | No |
| `"disabled"` | Dark gray | No |

#### `set_state(state, tooltip)`

Sets color and pulse behavior. Non-pulsing states display a static colored dot. Pulsing states animate `_pulse_val` (0.0–1.0) via `QVariantAnimation` using a sine-wave-based easing (`sin(val * π)`) for a "breathing" effect.

#### `paintEvent(event)`

Renders the dot as a filled circle with a radial gradient glow around it. The glow intensity scales with `_pulse_val`. Uses `QPainter` with `Antialiasing` and `SmoothPixmapTransform`.

---

### `MultitoonTab` (QWidget)

The main controller. Manages 4 toon slot cards.

#### State

| Attribute | Type | Description |
|-----------|------|-------------|
| `enabled_toons` | `list[bool]` (4) | Per-slot enable state |
| `chat_enabled` | `list[bool]` (4) | Per-slot chat broadcast toggle |
| `toon_names` | `list[str|None]` (4) | Names from Companion App |
| `keep_alive_enabled` | `list[bool]` (4) | Per-slot keep-alive toggle |
| `keep_alive_keys` | `list[str]` (4) | Per-slot keep-alive key |
| `keep_alive_delay` | `list[int]` (4) | Per-slot keep-alive interval (seconds) |
| `portrait_widgets` | `list[ToonPortraitWidget]` | One per slot |
| `pulsing_dots` | `list[PulsingDot]` | One per slot |

#### `build_ui()`

Builds a card for each toon slot. Each card contains:
- `ToonPortraitWidget` (top-left)
- `PulsingDot` status indicator
- Toon name label
- Enable toggle button
- Chat toggle button
- Movement mode selector (keymap set)
- Keep-alive row (key, delay, enable)

#### `refresh_theme()`

Applies theme colors to all widgets. `get_theme_colors()` → per-widget `setStyleSheet()` pattern, same as other tabs.

#### `apply_visual_state(index)`

Determines the visual state for slot `index`:
- No window: all controls disabled, dot = `"disabled"`
- Window found, service not started: dot = `"found"`, controls limited
- Enabled + active: dot = `"active"` or `"keep_alive"`
- Service running, not enabled: dot = `"found"`, can enable

#### Service Control

`toggle_service()`, `start_service()`, `stop_service()` — same pattern as v1.5. Start auto-enables toons with windows. Stop disables all.

#### Companion App Names

`_fetch_names_if_enabled()` → `get_toon_names_threaded()` (TTR) or `cc_api.get_toon_names_threaded()` (CC stub). Generation counter prevents stale callbacks.

#### Profile Load/Save

`save_profile(index)` reads current state into a `ToonProfile` and calls `ProfileManager.save_profile()`.
`load_profile(index)` reads from `ProfileManager` and applies enabled toons + movement modes. Called by `main.py.load_profile_slot()`.

#### Keep-Alive (per-toon)

Each toon slot has its own keep-alive: a key, delay interval, and enable toggle. When enabled, a per-toon timer fires `send_keep_alive_to_window()` on `InputService` targeting that slot's window. This replaces the global keep-alive from v1.5's Extras tab.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `services/input_service.py` | Input broadcasting service |
| `utils/theme_manager.py` | Theme colors, icon generation |
| `utils/ttr_api.py` | TTR companion name fetching |
| `utils/cc_api.py` | CC stub name fetching |
| `utils/game_registry.py` | Determining which API to use per window |
| `utils/profile_manager.py` | Save/load profiles |
| `utils/symbols.py` | Emoji fallback |

---

## Known Issues / Technical Debt

- Still large — portrait widget, pulsing dot, keep-alive, and toon control logic are all in one file.
- `ToonPortraitWidget._fetch` uses a thread but there's no connection pooling or caching beyond the `_fetch_token` generation guard.
- The "movement mode selector" maps to keymap set names from `KeymapManager`, but the UI label says "Set 1", "Set 2", etc. — not user-editable names. If the user renames sets in `KeymapTab`, the multitoon dropdown doesn't reflect those names automatically without a refresh.
