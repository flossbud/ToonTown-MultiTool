## ToonTown MultiTool v0.6.0-alpha.6

Patch release fixing the in-app updater on the Flatpak build.

---

### Bug Fixes

- Checking for updates on the Flatpak build now opens the update in your terminal correctly. It previously reported "Couldn't find a terminal emulator" even when one was installed.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.6.0-alpha.6-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.6.0-alpha.6-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.6.0-alpha.6-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.6.0-alpha.6-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.6.0-alpha.6-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.6.0-alpha.6
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
