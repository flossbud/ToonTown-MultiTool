## ToonTown MultiTool v0.6.0-alpha.5

Adds automatic game-file verification for both games and fixes Flatpak clipboard and config issues.

---

### Bug Fixes

- Corporate Clash now launches from the Flatpak build; it could previously fail to open its game window.
- Copying error details from the launch-failure dialog now works on the Flatpak build under Wayland.
- Bottles and Lutris configurations are now read correctly on the Flatpak build.

### Improvements

- Corporate Clash now verifies and repairs its game files automatically before launch, so a stale install no longer fails to start. If an update cannot finish, you are prompted to open the official launcher.
- Toontown Rewritten now verifies and repairs its game files automatically before launch.
- Clarified the Keep-Alive feature warning.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.6.0-alpha.5-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.6.0-alpha.5-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.6.0-alpha.5-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.6.0-alpha.5-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.6.0-alpha.5-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.6.0-alpha.5
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
