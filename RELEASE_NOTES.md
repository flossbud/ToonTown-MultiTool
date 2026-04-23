## ToonTown MultiTool v2.0.1

Patch release with stability and compatibility fixes for packaged builds.

---

### Bug Fixes

- Fixed AppImage crash (SIGSEGV) on Wayland when typing or pressing certain keys
- Fixed toon portraits not loading in packaged builds (Windows EXE and Linux AppImage)
- Fixed credential storage not detecting all available keyring backends in the AppImage
- Fixed Windows EXE opening a visible console window alongside the app

### Improvements

- Native Wayland support for Linux -- the app now uses the Wayland display backend automatically
- Wayland users no longer need the `QT_QPA_PLATFORM=xcb` workaround from v2.0.0
- Added missing keyring dependencies to support GNOME, Cinnamon, and other desktop environments in AppImage builds

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.1-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.1-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
