# ToonTown MultiTool v2 — Codebase Overview

## Purpose

ToonTown MultiTool v2 is a cross-platform desktop utility for multiboxing **Toontown Rewritten (TTR)** and **Corporate Clash (CC)** on Linux and Windows. It provides:

- **Account management**: Login, 2FA, queue handling, secure credential storage via OS keyring for both TTR and CC
- **Game launching**: Launches TTR/CC engine instances with credentials injected via env vars (TTR) or CLI args (CC)
- **Input broadcasting**: Captures keyboard from the focused game window and sends it to up to 3 background windows simultaneously, with per-toon custom keymaps
- **Invasion tracker**: Real-time TTR invasion data from the public API
- **Companion App integration**: Displays toon names from TTR's local API
- **Keep-alive**: Timer-triggered keypresses to prevent AFK disconnection
- **Profiles**: 5 named profiles storing toon enable/movement-mode configurations

`APP_VERSION = "2.0"`

---

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux X11 | Fully supported | Xlib backend preferred |
| Linux Wayland (GNOME) | Fully supported | Xlib required; xdotool triggers portal auth prompts |
| Linux Wayland (KDE) | Fully supported | Xlib preferred |
| Windows | Fully supported | Win32Backend (PostMessage) |
| macOS | Not supported | — |

---

## File Structure

```
ToonTownMultiTool/
├── main.py                         # App entry point, sidebar nav, QMainWindow
│
├── services/
│   ├── cc_launcher.py              # Corporate Clash process launcher + monitor
│   ├── cc_login_service.py         # CC login flow (HTTP, 2FA)
│   ├── hotkey_manager.py           # Global hotkey listener (pynput), profile load hotkeys
│   ├── input_service.py            # Core input broadcasting engine (threaded)
│   ├── launcher_env.py             # Safe environment builder for child processes
│   ├── ttr_launcher.py             # TTR engine process launcher + monitor
│   ├── ttr_login_service.py        # TTR login flow (HTTP, queue, 2FA)
│   └── window_manager.py           # Game window detection, active window polling
│
├── tabs/
│   ├── credits_tab.py              # About/credits display
│   ├── debug_tab.py                # Multi-category log viewer
│   ├── invasions_tab.py            # Real-time TTR invasion tracker
│   ├── keep_alive_tab.py           # Quick-launch tab (keep-alive moved to multitoon)
│   ├── keymap_tab.py               # Custom movement key set editor
│   ├── launch_tab.py               # Account management + game launching for TTR/CC
│   ├── multitoon_tab.py            # Main controller: toon cards, portraits, keep-alive
│   └── settings_tab.py             # App settings with iOS-style controls
│
└── utils/
    ├── __init__.py                 # Package marker
    ├── cc_api.py                   # CC companion API stub (no-op, CC has no local API)
    ├── credentials_manager.py      # OS keyring credential storage (635 lines)
    ├── game_registry.py            # Singleton: maps PIDs → game type (TTR/CC)
    ├── keymap_manager.py           # Movement key set definitions + translation
    ├── models.py                   # AccountCredential, ToonProfile dataclasses
    ├── profile_manager.py          # 5 named profiles (enabled toons + movement modes)
    ├── settings_manager.py         # JSON settings persistence with change callbacks
    ├── symbols.py                  # Runtime emoji/symbol rendering detection
    ├── theme_manager.py            # Colors, QSS, programmatic icon generation (large)
    ├── ttr_api.py                  # TTR Companion App API client (XRes, port scanning)
    ├── win32_backend.py            # Windows input backend (PostMessage WM_KEYDOWN/UP)
    └── xlib_backend.py             # Linux X11 input backend (send_event KeyPress/Release)
```

---

## Architecture Overview

### Application Layout

v2 replaced the flat tab bar of v1.5 with a **sidebar navigation** layout:

```
┌────────────┬──────────────────────────────┐
│  Header    │                              │
├────┬───────┤                              │
│    │  Nav  │    QStackedWidget            │
│    │  btn  │    (current tab content)     │
│    │  btn  │                              │
│    │  btn  │                              │
│    │  btn  │                              │
│    │  btn  │                              │
│    ├───────┤                              │
│    │  Logs │                              │
│    │ Credits│                             │
│    │ Hints │                              │
└────┴───────┴──────────────────────────────┘
```

Tab switching uses a fade-in animation on the stacked widget. Nav buttons have an animated icon-size hover effect (`AnimatedNavButton`).

### Data Flow: Input Broadcasting

```
User presses key on keyboard
        │
        ▼
HotkeyManager (pynput global Listener)
        │  normalize_key() → key string
        │  ├── Ctrl+1-5 → emit profile_load_requested
        ▼
key_event_queue (queue.Queue)
        │
        ▼
InputService.run() thread
        │  should_send_input() [via WindowManager]
        │  keymap translation: Set-1 key → target set key
        │  chat state, modifier, movement routing
        ▼
_send_via_backend(action, win_id, keysym, mods)
        │
        ├── XlibBackend.send_keydown/up/key()   ← Linux
        └── Win32Backend.send_keydown/up/key()  ← Windows
```

### Login & Launch Flow

```
User enters credentials in LaunchTab
        │
        ▼
TTRLoginWorker / CCLoginWorker (background thread)
        │  HTTP POST → TTR/CC API
        │  handle queue (TTR only), 2FA
        │  emit login_success(gameserver, cookie/osst_token)
        ▼
TTRLauncher / CCLauncher
        │  validate engine path (trusted dir check)
        │  build_launcher_env() → safe child env
        │  subprocess.Popen(TTREngine / CorporateClash)
        │  register PID in GameRegistry
        ▼
game process running
        │
        ▼
WindowManager.assign_windows() detects new window
        │  emit window_ids_updated(list)
        ▼
MultitoonTab.update_toon_controls()
        │  TTR: fetch toon name via ttr_api
        │  CC: cc_api stub returns None
```

### Keymap Translation

v2 introduces per-toon custom movement key sets. Instead of the fixed WASD/ARROWS modes:

- **Set 1** = the user's physical keys (what they press)
- **Set 2–8** = target toon's expected keys

When user presses W (Set-1 "up"), input_service translates this to whatever Set-2's "up" direction key is, and sends that to toon 2's window. This enables arbitrary key mappings per toon.

Legacy WASD/ARROWS strings from v1.5 still work — input_service falls back to the old mode logic when keymap_manager is None.

### Credential Security

Credentials are stored via **OS keyring** (Secret Service on Linux, Credential Locker on Windows):
- Metadata (label, username, game type) → `~/.config/toontown_multitool/accounts.json`
- Passwords → keyring (never written to disk in plaintext)
- On keyring failure: in-memory fallback (passwords lost on restart, no crash)
- v1 migration: if old encrypted credential file exists, migrates to keyring on first run

---

## Key Design Decisions & Gotchas

### Xlib vs xdotool (Linux)
Same as v1.5: xdotool triggers GNOME RemoteDesktop portal auth dialogs per subprocess. Xlib sends from the already-authorized Python process. xdotool is still used for window discovery (read-only calls, no portal trigger).

### XRes Extension for PID Resolution
v2 upgraded the port→window mapping in `ttr_api.py` and `xlib_backend.py` to use the X Resource Extension (`XRes.GetClientPid`) to get the **host PID** for a window directly, bypassing the NSpid/namespace mapping step needed in v1.5. This is more reliable for Flatpak instances.

### Win32 PostMessage (Windows)
On Windows, `win32gui.PostMessage(hwnd, WM_KEYDOWN, vk, lparam)` is used instead of SendMessage. PostMessage is asynchronous and non-blocking — it doesn't steal focus or wait for the target window to process the message.

### Phantom Chat Detection
The input service detects "stealth whisper" scenarios: after 3 printable characters are typed without the chat box being open, it enters phantom mode and stops broadcasting further typing. Pressing Escape or Return exits phantom mode. This prevents accidentally broadcasting private whisper replies to all toons.

### Chat Idle Timeout
If a toon's chat box has been open for 15 seconds without any typing activity, the service sends Escape to background toons to auto-close their chat boxes. This prevents stuck-open chat on background toons.

### Game Registry Singleton
`GameRegistry` maps PIDs to game type (TTR or CC). Used by `WindowManager` to correctly classify discovered windows as TTR or CC, which determines which API to use for name fetching. Without this, two games with different window class names need different detection strategies.

### Launcher Environment (`launcher_env.py`)
Uses an allowlist approach — only known-safe environment variables are passed to game subprocesses. This prevents developer secrets (AWS keys, GitHub tokens, etc.) from leaking into game processes via environment inheritance.

### Engine Path Validation
Both `TTRLauncher` and `CCLauncher` validate the engine executable path against a trusted directory allowlist before running it. This prevents a malicious file from being executed if someone manipulates the path setting.

---

## Configuration Files

All config files live in `~/.config/toontown_multitool/`:

| File | Contents |
|------|----------|
| `settings.json` | App settings (theme, backend, active_profile, etc.) |
| `accounts.json` | Account metadata (label, username, game — NO passwords) |
| `profiles.json` | 5 named profiles with enabled toons + movement modes |
| `keymaps.json` | Custom movement key sets |
| `presets.json` | Legacy v1.5 presets (migrated to profiles on first run) |

Passwords are stored in the OS keyring under service name `"toontown_multitool"`.

---

## Known Technical Debt

- `multitoon_tab.py` is still large — toon portrait rendering, pulsing dots, keep-alive logic, and toon control UI are all in one file.
- `credentials_manager.py` at 635 lines handles too many concerns (probe, migration, recovery, diagnostics).
- `keep_alive_tab.py` in v2 is mostly a launch shortcut — the actual keep-alive logic moved into `multitoon_tab.py` but the tab still exists as a placeholder.
- `tabs/settings_tab.py` imports `IOSSegmentedControl` from itself and it's also used by `debug_tab.py` — a helper widget that belongs in utils or a shared widgets module.
- The `Plans/`, `Reports/`, `old-code/`, and `test_*.py` files should be removed from the main project tree before v2 release.
- `ToonTownMultiTool.exe` binary is committed to the repo — large binaries should not be in git.
