# 🎮 ToonTown MultiTool

A polished multitoon input controller for **Toontown Rewritten** on Linux, designed to work beautifully on modern systems using **Wayland** or **X11**.

Built in Python + PySide6.

---

## ✨ Features

- ✅ Multitoon input broadcasting (up to 4 toons)
- 🎮 Per-toon WASD / ARROW movement key mapping
- 🔁 Auto "Keep-Alive" keypress (Extras tab)
- 💾 Save & load presets (Ctrl+1–5 hotkeys)
- 🖌️ Light & Dark themes with auto-updating styles
- 🪟 Auto-detects valid TTR windows only
- 🚀 Launch Toontown Rewritten directly from the UI


---

## ⚙️ Installation

1. 🔧 Developer (Python)

```
git clone https://github.com/yourusername/toontown-multitool.git
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

- Works on KDE Plasma, GNOME, XFCE, i3, etc.
- Compatible with **Wayland** and **X11**
- Requires `xdotool` installed:
  - Arch: `sudo pacman -S xdotool`
  - Debian/Ubuntu: `sudo apt install xdotool`

---

## 🧠 Limitations

- No support for Windows or macOS (coming soon...)
- Flatpak input passthrough depends on environment

---

## 🔐 License

MIT License – free to use, share, modify.

---

## 👤 Author

Made by **flossbud**  
Open issues or reach out for ideas and improvements.
