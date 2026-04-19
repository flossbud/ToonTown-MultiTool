# tabs/debug_tab.py

## Purpose

Multi-category log viewer with a segmented control to switch between log categories. In v2, replaces the single plain text log of v1.5 with three separate log views: Raw Terminal, Input Service, and TTR API.

---

## Class: `DebugTab` (QWidget)

### Attributes

```python
logging_enabled: bool  # master switch; if False, append_log() is a no-op
```

### UI Structure

```
DebugTab (QWidget, VBox)
├── IOSSegmentedControl  ← "Terminal" | "Input" | "TTR API"
└── QStackedWidget
    ├── log_terminal     ← QPlainTextEdit (general/untagged messages)
    ├── log_input        ← QPlainTextEdit ([Input], [KeepAlive], [Hotkey], [Service])
    └── log_api          ← QPlainTextEdit ([TTR API], [Profile], [Launch])
```

`IOSSegmentedControl` is imported from `tabs/settings_tab.py` — a cross-tab widget dependency.

### `_create_log_widget()` → QPlainTextEdit

Creates a read-only `QPlainTextEdit` with:
- Monospace font, 11px
- Dark background `#1e1e1e`, light text `#ccc` (hardcoded dark, theme-independent)
- `QGraphicsDropShadowEffect` for visual depth
- `setMaximumBlockCount(2000)` — limits log to 2000 lines to prevent unbounded memory growth (fixed v1.5's unbounded growth issue)

### `_on_tab_changed(idx)`

Switches the stacked widget to the corresponding log page (0=Terminal, 1=Input, 2=API).

### `append_log(message)`

Routes the message to the appropriate log based on tag detection:

| Tag in message | Target log |
|---------------|-----------|
| `[Input]`, `[KeepAlive]`, `[Hotkey]`, `[Service]` | Input Service log |
| `[TTR API]`, `[Profile]`, `[Launch]` | TTR API log |
| Anything else | Raw Terminal log |

Prepends `[HH:MM:SS]` timestamp. Auto-scrolls the target log to the bottom.

If `logging_enabled` is False, the method returns immediately without logging.

---

## Key Changes from v1.5

- Three separated log categories (was single plain text)
- `setMaximumBlockCount(2000)` prevents unbounded memory growth
- `logging_enabled` flag (was always-on)
- `IOSSegmentedControl` tab switcher
- Dark styling still hardcoded (same as v1.5 — not theme-responsive)

---

## Known Issues / Technical Debt

- Imports `IOSSegmentedControl` from `tabs/settings_tab.py` — cross-tab dependency. This widget should live in a shared module.
- Log views remain hardcoded dark-on-dark regardless of the app's light/dark theme setting.
- `logging_enabled = False` requires the caller to have a reference to the tab and set this attribute directly — no signal or settings integration.
