## ToonTown MultiTool v0.7.0-alpha.2

Adds Windows support for strict keyset separation and fixes the Flatpak updater.

---

### Bug Fixes

- In-app update on Flatpak now installs the new version. It previously looked like nothing happened (the app just restarted on the old version).

### Improvements

- Strict keyset separation (TTR) now works on Windows, not just Linux. Each TTR window keeps responding to its own assigned movement keys no matter which window is in front.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.7.0-alpha.2-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.7.0-alpha.2-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.7.0-alpha.2-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.7.0-alpha.2-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.7.0-alpha.2-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.7.0-alpha.2
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
