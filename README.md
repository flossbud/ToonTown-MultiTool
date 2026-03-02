# 🎮 ToonTown MultiTool

A multitoon input controller for **Toontown Rewritten** on Linux, designed for both **KDE** and **GNOME** on **Wayland** or **X11**.

Built in Python + PySide6.

---

## ✨ Features

- ✅ Multitoon input broadcasting (up to 4 toons)
- 🎮 Per-toon WASD / ARROW movement key mapping
- 💬 Per-window chat toggle — enable or disable chat input independently for each toon
- 🧠 Companion App support — automatically detects and displays toon names from TTR's local API
- 🔁 Auto "Keep-Alive" keypress (Extras tab)
- 💾 Save & load presets (Ctrl+1–5 hotkeys)
- 🖌️ Light & Dark themes with auto-updating styles
- 🪟 Auto-detects valid TTR windows only
- 🚀 Open Toontown Rewritten Launcher(s) directly from the UI

---

## 🐧 Platform Support

| Platform | Status |
|---|---|
| KDE Plasma — X11 | ✅ Fully supported |
| KDE Plasma — Wayland | ✅ Fully supported |
| GNOME — X11 | ✅ Fully supported |
| GNOME — Wayland | ✅ Fully supported (v1.5+) |

---

## ⚙️ Installation

### 1. 📦 AppImage (recommended)

Download the latest `ToonTownMultiTool-x86_64.AppImage` from the [Releases](../../releases) page.

```bash
chmod +x ToonTownMultiTool-x86_64.AppImage
./ToonTownMultiTool-x86_64.AppImage
```

> If you're on GNOME Wayland and the app doesn't launch, run with:
> ```bash
> QT_QPA_PLATFORM=xcb ./ToonTownMultiTool-x86_64.AppImage
> ```

---

### 2. 🔧 Developer (Python)

```bash
git clone https://github.com/flossbud/toontown-multitool.git
cd toontown-multitool
pip install -r requirements.txt
python main.py
```

---

### 3. 🏗️ Build from Source

```bash
# Build binary
pyinstaller --noconfirm --clean --onefile --windowed --name "ToonTownMultiTool" main.py

# Build AppImage (requires appimagetool in ~/)
cp dist/ToonTownMultiTool AppDir/usr/bin/
~/appimagetool AppDir ToonTownMultiTool-x86_64.AppImage
```

---

## 📋 Dependencies

- Python 3.9+
- PySide6
- pynput
- python-xlib
- `xdotool` (required for window detection)
- `flatpak` + TTR launcher (optional, for Launch button)

Install system packages:

```bash
# Fedora
sudo dnf install xdotool

# Ubuntu / Debian
sudo apt install xdotool

# Arch
sudo pacman -S xdotool
```

Install Python packages:

```bash
pip install PySide6 pynput python-xlib
```

---

## 🧠 Companion App Support

ToonTown MultiTool integrates with TTR's local Companion App API to automatically detect and display the name of the toon logged in on each window. When you start the service, TTR will prompt you to authorize the connection — approve it once and names will update automatically every 5 seconds.

Companion App support can be toggled in **Settings → Advanced → Enable Companion App Support**.

---

## 💬 Per-Window Chat Toggle

Each toon slot has an independent chat toggle button. When chat is enabled for a toon, keyboard input (letters, numbers, symbols) is forwarded to that window in addition to movement keys. When disabled, only movement keys are sent — useful for toons you want to keep moving without accidentally typing in their chat box.

---

## 🔧 Input Backend

By default, ToonTown MultiTool uses **Xlib** for input sending. This is a direct X11 call that works seamlessly on all supported platforms including GNOME Wayland, with no authorization prompts.

If needed, you can switch to **xdotool** in **Settings → Advanced → Input Backend**. Note that xdotool on GNOME Wayland will trigger repeated Remote Desktop authorization prompts and is not recommended.

---

## 🔐 License

MIT License – free to use, share, modify.

---

## 👤 Author

Made by **flossbud**  
Open issues or reach out for ideas and improvements.
