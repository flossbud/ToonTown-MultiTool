# tabs/keep_alive_tab.py

## Purpose

In v2, `KeepAliveTab` is a simplified placeholder tab. The actual keep-alive logic (per-toon timer + key send) was moved into `MultitoonTab`. This tab now only provides a quick-launch shortcut for TTR and some UI chrome.

---

## Class: `KeepAliveTab` (QWidget)

### UI

```
KeepAliveTab (QWidget, VBox)
├── Tip label   ← "Keep-alive is now configured per-toon in the Multitoon tab"
└── Launch TTR button
```

### `launch_ttr()`

Runs `flatpak run com.toontownrewritten.Launcher` via `subprocess.Popen` using an environment built by `launcher_env.build_launcher_env({"QT_QPA_PLATFORM": "xcb"})`. Forces X11 mode for the TTR launcher, same reasoning as v1.5 — prevents Flatpak launcher from failing on Wayland sessions.

Uses `Popen` (non-blocking) rather than `run` — the launch is fire-and-forget.

### `refresh_theme()`

Minimal theme application — background color and button style.

---

## Key Changes from v1.5

- All keep-alive logic removed (moved to `MultitoonTab`)
- `KeyCaptureLineEdit` and `NonToggleableCheckBox` removed
- Tab is now primarily a TTR launcher button with a tip redirecting users to MultitoonTab

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/theme_manager.py` | Theme colors |
| `utils/symbols.py` | Emoji fallback for launch button |
| `services/launcher_env.py` | Clean environment for Flatpak launch |
