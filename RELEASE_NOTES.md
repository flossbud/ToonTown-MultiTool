## ToonTown MultiTool v2.0.4

Patch release fixing the Flatpak launch flow on Wayland desktops.

---

### Bug Fixes

- Fixed the Flatpak crashing on startup on Wayland desktops (KDE Plasma, GNOME).
- Fixed the Flatpak being unable to find Toontown Rewritten when installed via the official TTR launcher Flatpak.
- Fixed the Flatpak silently failing to launch the game after a successful login.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.4-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.4-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |
| `TTMultiTool-v2.0.4-Linux-x86_64.flatpak` | Linux Flatpak |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
