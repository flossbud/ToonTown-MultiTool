## ToonTown MultiTool v2.0.2

Patch release with stability and UI polish fixes.

---

### Bug Fixes

- Fixed an issue where saved account credentials could fail to load on Linux after a reboot.
- Fixed status indicator dots being vertically misaligned with the "Sending input to X toons" label.
- Fixed long toon names causing the jellybean count to be cut off in the toon card.

### Improvements

- Added a system-wide desktop entry so the app appears in application menus when installed.
- Added an always-on credentials diagnostic log to make future credential issues easier to investigate.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.2-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.2-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
