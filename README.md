# 🎮 ToonTown MultiTool

A multiboxing controller for **Toontown Rewritten** and **Corporate Clash** on Linux and Windows.

Built with Python + PySide6.

---

## ✨ What's New in v2.0

**🪟 Windows Support**
- v2.0 adds full Windows support

**⌨️ Custom Movement Key Sets**
- v2.0 lets each slot use a different key set, and reads the default configuration for input translation
- Up to 8 named key sets, fully customisable in the new Keymap tab
  
**🐾 TTR Companion App Integration**
- Live toon name, laff, and jellybean count per slot in the Multitoon tab
- Toon portrait images fetched and cached from the Rendition API

**🚨 Invasion Tracker**
- Live cog invasion display, updated every 60 seconds

**💾 Session Profiles**
- 5 named profiles storing which toon slots are active
- Load via Ctrl+1–5 hotkeys or change via icons on the main tab, replacing the old Preset system

**⚡ Input Backend**
- Keystrokes now sent via Xlib `send_event` directly — no more `xdotool` subprocess per keypress, fixing GNOME Wayland portal auth prompts

**🔐 Account Manager**
- Store up to 16 TTR and CC accounts with one-click launch
- Passwords stored exclusively in the OS keyring, never written to disk
- Handles TTR login queues and 2FA automatically

**🎮 Corporate Clash Support**
- Launch, log in to, and multibox CC alongside TTR
- The app automatically identifies which game each window belongs to

---

## 🕹️ Features

**Multitoon Control**
- Broadcast keyboard input to up to 4 background toons simultaneously
- Per-toon movement key mapping! Each toon can use a different key set (WASD, Arrows, or fully custom)
- Up to 8 custom key sets
- Per-toon keep-alive timer with configurable key and interval

**Game Support**
- Toontown Rewritten — form-based login, queue polling, Flatpak Launcher
- Corporate Clash — JSON API login, CLI credential injection
  
**Account Management**
- Store up to 16 TTR and CC accounts with secure OS keyring storage (Secret Service on Linux, Credential Locker on Windows)
- Passwords never written to disk - keyring only
- One-click launch with automatic credential injection

**Companion App Integration (TTR)**
- Displays toon names, laff points, and jellybean counts live from the TTR Local API
- Toon portrait images via the Rendition API
- Works correctly with multiple Flatpak TTR instances using XRes PID resolution

**Session Profiles**
- 5 named profiles storing which toons are enabled
- Load profiles via hotkeys (Ctrl+1 through Ctrl+5)

**UI**
- Sidebar navigation with animated transitions
- Light and dark themes (auto-detects from system)
- Invasion tracker with live department status

---

## ⚙️ Requirements

**🐧 Linux:**
- Python 3.10+
- PySide6, pynput, python-xlib
- `xdotool` (window detection only, not required for input)
- Secret Service-compatible keyring (GNOME Keyring or KWallet)

**🪟 Windows:**
- Python 3.10+
- PySide6, pynput, pywin32

---

## Installation

### Run from source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```

### Linux — Wayland sessions

```bash
QT_QPA_PLATFORM=xcb python main.py
```

---

## Platform Notes

### Linux
- Tested on Fedora (KDE Plasma, GNOME) with Wayland and X11
- Flatpak TTR instances fully supported via XRes PID resolution
- KWallet and GNOME Keyring both supported

### Windows
- Input via Win32 `PostMessage`, no focus stealing
- Corporate Clash supported alongside TTR

---

## Configuration

Config files at `~/.config/toontown_multitool/`:

| File | Contents |
|------|----------|
| `settings.json` | App preferences |
| `accounts.json` | Account metadata (no passwords) |
| `keymaps.json` | Custom movement key sets |
| `profiles.json` | Named session profiles |

---

## License

MIT License — free to use, share, and modify.

---

## Author

Made by **flossbud**
