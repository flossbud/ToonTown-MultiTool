# ToonTown MultiTool v2.0.0

v2.0 is a complete rewrite. Same concept -- multiboxing input control for Toontown -- rebuilt from the ground up with security hardening, reliability improvements, and cross-platform support.

---

## What's New

**Corporate Clash Support**
- Launch, log in to, and multibox CC alongside TTR
- The app automatically identifies which game each window belongs to

**Account Manager**
- Store up to 16 TTR and CC accounts with one-click launch
- Passwords stored exclusively in the OS keyring (GNOME Keyring / KWallet on Linux, Credential Locker on Windows), never written to disk
- CC auth tokens passed via environment variable, never exposed in process arguments
- Handles TTR login queues and 2FA automatically
- Concurrent 2FA prompts prevented per account slot

**TTR Companion App Integration**
- Live toon name, laff, and jellybean count displayed per slot in the Multitoon tab
- Toon portrait images fetched and cached from the Rendition API
- Correctly identifies multiple Flatpak TTR instances using XRes PID resolution

**Custom Movement Key Sets**
- v1.5.1 assumed all toons used WASD -- v2.0 lets each slot use a different key set
- Up to 8 named key sets, fully customizable in the new Keymap tab
- Default sets: WASD and Arrow Keys

**Invasion Tracker**
- Live cog invasion display, updated every 60 seconds from the TTR public API

**Session Profiles**
- 5 named profiles storing which toon slots are active, plus keep-alive and rapid-fire state
- Load instantly via Ctrl+1 through Ctrl+5 hotkeys
- Replaces the old Preset system

**Windows Support**
- v1.5.1 was Linux-only -- v2.0 adds full Windows support
- Win32 input backend sends keystrokes to background windows without stealing focus

---

## Changes from v1.5.1

- **Input backend** -- keystrokes now sent directly via Xlib `send_event` instead of spawning an `xdotool` subprocess per keypress; fixes GNOME Wayland portal auth prompts. `xdotool` is still used for window detection only.
- **Navigation** -- flat tab bar replaced with an animated sidebar
- **Keep-alive** -- moved from the Extras tab into per-toon controls in the Multitoon tab
- **Presets to Profiles** -- renamed and expanded with hotkey support

---

## Security

- CC authentication token passed via environment variable instead of CLI argument (was visible in `ps`)
- Thread-safe locks on shared global state in TTR API module
- In-memory password fallback has a 1-hour TTL with user-facing warnings
- Network error messages sanitized, no infrastructure details leaked to the UI
- HTTPS enforcement assertions on all login API URLs
- Settings file written with `0600` permissions

## Reliability

- Chat state properly reset when game window loses focus
- Key events use blocking queue put with timeout instead of silent drop
- V1 credential migration archives old file instead of deleting before verification
- Keyring probe auto-triggers deferred v1 migration on completion
- Cumulative 5-second timeout on keyring backend recovery (prevents UI hang)
- Proper thread shutdown hooks for InputService and InvasionsTab
- Stale worker/launcher references nulled after signal disconnect
- xdotool timeout preserves previous active window instead of clearing
- Engine path validation checks file existence after symlink resolution
- Empty usernames rejected in account editor

## Error Handling

- Bare `except` clauses replaced with specific exceptions across 5 files
- All caught exceptions now logged instead of silently swallowed
- Accounts with missing IDs skipped with warning instead of creating empty entries
- Index bounds check added for chat management loop

---

## Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.0-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.0-Linux-x86_64.AppImage` | Linux (X11 / Wayland via XWayland) |

**Linux:** If running on a Wayland session, launch with `QT_QPA_PLATFORM=xcb ./TTMultiTool-v2.0.0-Linux-x86_64.AppImage`
