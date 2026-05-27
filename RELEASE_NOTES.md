## ToonTown MultiTool v0.6.0-alpha.4

Patch release fixing the AppImage taskbar icon and ensuring the app exits
cleanly when the main window is closed.

---

### Bug Fixes

- AppImage launches no longer show the old cached taskbar icon. The bundled
  icon is now used directly, bypassing the host icon theme.
- Closing the main window now fully shuts down the app. Previously, background
  services could keep the process alive after the window was dismissed.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.6.0-alpha.4-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.6.0-alpha.4-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.6.0-alpha.4-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.6.0-alpha.4-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.6.0-alpha.4-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.6.0-alpha.4
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
