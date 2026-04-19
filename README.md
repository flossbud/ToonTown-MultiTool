# 🎮 ToonTown MultiTool

A multitoon input controller for **Toontown Rewritten** on Linux, designed to work on systems using **Wayland** or **X11**.

Built in Python + PySide6.

---

## ✨ Features

- ✅ Multitoon input broadcasting (up to 4 toons)
- 🎮 Per-toon WASD / ARROW movement key mapping
- 🔁 Auto "Keep-Alive" keypress (Extras tab)
- 💾 Save & load presets (Ctrl+1–5 hotkeys)
- 🖌️ Light & Dark themes with auto-updating styles
- 🪟 Auto-detects valid TTR windows only
- 🚀 Open Toontown Rewritten Launcher(s) directly from the UI

---

## ⚙️ Installation

1. 🔧 Developer (Python)

```
git clone https://github.com/flossbud/toontown-multitool.git
cd toontown-multitool
pip install -r requirements.txt
python main.py
```

---

2. 📦 Build Executable

To package a standalone binary using PyInstaller:

```
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name "ToonTownMultiTool" main.py
```

Output will be in: `./dist/ToonTownMultiTool`

---

3. 📋 Dependencies

- Python 3.9+
- PySide6
- pynput
- `xdotool` (required for input simulation)
- `flatpak` + TTR launcher (optional for Launch button)

---

## 🐧 Linux Notes

- Works on **KDE Plasma** (e.g. Fedora KDE)
- Works on **GNOME** (e.g. Ubuntu Desktop)
- Compatible with **Wayland** and **X11**
- Requires `xdotool` installed:
  - Arch: `sudo pacman -S xdotool`
  - Ubuntu/Debian: `sudo apt install xdotool`
  - Fedora: `sudo dnf install xdotool`

For Wayland users, force X11 compatibility with:

```
QT_QPA_PLATFORM=xcb ./ToonTownMultiTool-x86_64.AppImage
```

---

## 🧠 Limitations

- No support for Windows or macOS (Windows support coming soon)
- Flatpak input passthrough depends on environment
- This application assumes that you have your movement keybinds set to WASD for each TTR instance.
- The ability to manually adjust key assignments is planned for the next release.

---

## 🔐 License

MIT License – free to use, share, modify.

---

## 👤 Author

Made by **flossbud**  
Open issues or reach out for ideas and improvements.
