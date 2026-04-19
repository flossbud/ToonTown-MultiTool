# ToonTown MultiTool

A multiboxing controller for **Toontown Rewritten** and **Corporate Clash** on Linux and Windows.

Built with Python + PySide6.

---

## Features

**Multitoon Control**
- Broadcast keyboard input to up to 4 background toons simultaneously
- Per-toon movement key mapping — each toon can use a different key set (WASD, Arrows, or fully custom)
- Up to 8 custom key sets with named presets
- Per-toon keep-alive timer with configurable key and interval

**Companion App Integration (TTR)**
- Displays toon names, laff points, and jellybean counts live from the TTR Local API
- Toon portrait images via the Rendition API
- Works correctly with multiple Flatpak TTR instances using XRes PID resolution

**Session Profiles**
- 5 named profiles storing which toons are enabled and their movement modes
- Load profiles via hotkeys (Ctrl+1 through Ctrl+5)

**Account Management**
- Store up to 16 TTR and CC accounts with secure OS keyring storage (Secret Service on Linux, Credential Locker on Windows)
- Passwords never written to disk — keyring only
- One-click launch with automatic credential injection

**Game Support**
- Toontown Rewritten — form-based login, queue polling, Flatpak Launcher
- Corporate Clash — JSON API login, CLI credential injection

**UI**
- Sidebar navigation with animated transitions
- Light and dark themes (auto-detects from system)
- Invasion tracker with live department status

---

## Requirements

**Linux:**
- Python 3.10+
- PySide6
- pynput
- python-xlib
- `xdotool` (window detection only — not required for input)
- `ss` (iproute2, for TTR Companion App port detection)
- Secret Service-compatible keyring (GNOME Keyring or KWallet)

**Windows:**
- Python 3.10+
- PySide6
- pynput
- pywin32

---

## Installation

### Run from source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```

### Linux — Force X11 mode (Wayland)

If running on a Wayland session, launch with:

```bash
QT_QPA_PLATFORM=xcb python main.py
```

This is required because the Xlib input backend needs an X11 connection. The app works on GNOME and KDE Wayland sessions via XWayland.

---

## Platform Notes

### Linux

- Tested on Fedora (KDE Plasma, GNOME) with Wayland and X11
- Flatpak TTR instances are fully supported — PID resolution uses the XRes X11 extension to correctly identify each instance even when namespace PIDs collide
- Input is sent via direct Xlib `send_event` calls (no xdotool subprocess per keypress, avoiding GNOME portal auth prompts)
- KWallet and GNOME Keyring are both supported for credential storage

### Windows

- Input sent via Win32 `PostMessage` — no focus stealing
- Windows Credential Locker used for keyring storage
- Corporate Clash supported alongside TTR

---

## Configuration

All config files are stored in `~/.config/toontown_multitool/` (Linux) or the equivalent user config directory:

| File | Contents |
|------|----------|
| `settings.json` | App preferences (theme, backend, keep-alive settings) |
| `accounts.json` | Account metadata (no passwords) |
| `keymaps.json` | Custom movement key sets |
| `profiles.json` | Named session profiles |

Passwords are stored exclusively in the OS keyring — never in these files.

---

## License

MIT License — free to use, share, and modify.

---

## Author

Made by **flossbud**
