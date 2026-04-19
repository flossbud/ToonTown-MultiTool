# utils/symbols.py

## Purpose

Cross-platform emoji/symbol fallback utility. Some Linux distributions and older Windows systems don't have emoji-capable fonts installed. Rendering an emoji on such a system produces an invisible or blank character. This module detects rendering support at runtime and returns either the emoji/symbol or a plain-ASCII fallback.

---

## Detection Mechanism

Both detection functions use the same technique:

1. Allocate a 20×20 transparent `QPixmap`.
2. Draw the test character into it using the application's default font.
3. Scan all 400 pixels — if any pixel is non-zero (non-transparent), the character rendered visibly.
4. Cache the result globally (`_USE_EMOJI`, `_USE_MISC`) so detection only happens once per session.

This is more reliable than checking font names because it tests what the OS actually renders, including emoji fallback fonts the OS may provide automatically.

### `_emoji_supported()`

Tests `"✅"` — a high-codepoint emoji that requires an emoji-capable color font (Noto Color Emoji, Segoe UI Emoji, etc.).

### `_misc_supported()`

Tests `"↻"` — a BMP (Basic Multilingual Plane) symbol that most fonts include but some minimal/legacy setups omit.

---

## Public Functions

### `S(emoji, fallback) → str`

Returns `emoji` if the system can render emoji codepoints, otherwise `fallback`. Lazy: initializes `_USE_EMOJI` on first call.

**Usage examples:**
```python
S("✅", "[OK]")       # Checkmark or "[OK]"
S("🚀", "Launch")     # Rocket or "Launch"
S("⚠️", "Warning")   # Warning sign or "Warning"
```

### `M(symbol, fallback) → str`

Returns `symbol` if misc BMP symbols render, otherwise `fallback`. For non-emoji unicode like arrows.

**Usage examples:**
```python
M("↻", "Refresh")   # Circular arrow or "Refresh"
M("↑", "Up")        # Up arrow or "Up"
```

---

## Why Two Functions?

Emoji (`S`) and BMP misc symbols (`M`) require different font support levels:

- Emoji need color emoji fonts (often absent on minimal Linux installs).
- BMP symbols (`↻`, `↑`) are in most modern fonts but may be missing on very old setups.

A system might support BMP symbols but not emoji, so they're tested separately.

---

## Dependencies

- `PySide6.QtGui` — `QPixmap`, `QPainter`, `QFont`, `QColor`
- `PySide6.QtWidgets` — `QApplication` (for accessing the default font)

> **Note:** These functions require a running `QApplication` instance to work. They must not be called at import time or before the Qt application is initialized.

---

## Known Issues / Technical Debt

- Detection is done once at first call and cached for the session. If the user installs an emoji font while the app is running, the fallback won't update until restart.
- `_can_render()` creates a new `QPixmap` and `QPainter` each time it's called (twice, for the two test characters). This is acceptable since detection only happens once, but it does require a running display connection.
- The 20×20 pixel canvas may be too small for some very large emoji that don't render at 12pt size. In practice this hasn't been an issue since common status emoji render well at 12pt.
