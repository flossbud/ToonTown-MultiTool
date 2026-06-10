## ToonTown MultiTool v0.7.0-alpha.3

Adds four-mode chat handling, an F5 refresh hotkey, and Windows support for elevated games.

---

### Improvements

- Chat handling is now a Forwarding Logic selector in Settings with four modes (Focused Toon Only, All Toons, Keyset Dynamic, Per-Toon), each explained right in the card.
- Press F5 to refresh the detected toon list (with a short cooldown so repeated presses don't spam).
- On Windows, the app now detects when a game is running as administrator while the tool is not, shows a notice, and offers a one-click relaunch as administrator so multitooning keeps working.

### Bug Fixes

- Backspace pressed while chatting no longer reaches toons that are excluded from chat broadcasting.
- Custom keysets that rebind non-movement actions now send those keys only to the toon that owns the binding.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.7.0-alpha.3-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.7.0-alpha.3-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.7.0-alpha.3-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.7.0-alpha.3-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.7.0-alpha.3-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.7.0-alpha.3
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
