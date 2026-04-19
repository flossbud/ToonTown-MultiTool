# ToonTown MultiTool v2.0

v2.0 is a complete rewrite. Same concept — multiboxing input control for Toontown — rebuilt from the ground up.

---

## What's New

**Corporate Clash Support**
- Launch, log in to, and multibox CC alongside TTR
- The app automatically identifies which game each window belongs to

**Account Manager**
- Store up to 16 TTR and CC accounts with one-click launch
- Passwords stored exclusively in the OS keyring (GNOME Keyring / KWallet on Linux, Credential Locker on Windows) — never written to disk
- Handles TTR login queues and 2FA automatically

**TTR Companion App Integration**
- Live toon name, laff, and jellybean count displayed per slot in the Multitoon tab
- Toon portrait images fetched and cached from the Rendition API
- Correctly identifies multiple Flatpak TTR instances using XRes PID resolution

**Custom Movement Key Sets**
- v1.5.1 assumed all toons used WASD — v2.0 lets each slot use a different key set
- Up to 8 named key sets, fully customisable in the new Keymap tab
- Default sets: WASD and Arrow Keys

**Invasion Tracker**
- Live cog invasion display, updated every 60 seconds from the TTR public API

**Session Profiles**
- 5 named profiles storing which toon slots are active
- Load instantly via Ctrl+1–5 hotkeys
- Replaces the old Preset system

**Windows Support**
- v1.5.1 was Linux-only — v2.0 adds full Windows support
- Win32 input backend sends keystrokes to background windows without stealing focus

---

## Changes from v1.5.1

- **Input backend** — keystrokes now sent directly via Xlib `send_event` instead of spawning an `xdotool` subprocess per keypress; fixes GNOME Wayland portal auth prompts. `xdotool` is still used for window detection only.
- **Navigation** — flat tab bar replaced with an animated sidebar
- **Keep-alive** — moved from the Extras tab into per-toon controls in the Multitoon tab
- **Presets → Profiles** — renamed and expanded with hotkey support

---

## Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0-Linux-x86_64.AppImage` | Linux (X11 / Wayland via XWayland) |

**Linux:** If running on a Wayland session, launch with `QT_QPA_PLATFORM=xcb ./TTMultiTool-v2.0-Linux-x86_64.AppImage`
