## ToonTown MultiTool v0.8.0-alpha.2

Adds an app-wide light theme, a diagnostics Logs console, and feature discovery hints.

---

### Improvements

#### Light Theme

- The whole interface now follows a light theme when your system is set to light mode: the toon cards, the Keep-Alive capsule, the Keysets editor and keyboard, the account portraits, and the new Logs view. Dark mode looks exactly as before.
- Toon cards use a vivid per-game tint when active and a soft paper look when a toon is off or its game window is closed, in both light and dark themes.

#### Feature Discovery

- New discovery hints point out the Keep-Alive and Click-Sync tools, with a short explanation and a one-time confirmation before any background input is enabled.

#### Logs

- A new Logs view brings every part of the app into one live console, so troubleshooting no longer means digging through a terminal or a log file.
- It captures far more than the old log tab did, merging activity from across the app's services into a single stream and tagging each line with the source it came from and its severity.

---

### Bug Fixes

- The app now follows your system light and dark setting reliably, instead of occasionally locking onto its own theme.
- Turning Keep-Alive off and back on no longer leaves a card missing its controls.
- On GNOME, the Float UI radial menu and side panel now stay above the toon cards and are no longer clamped to the screen edge.
- The Launcher's empty-state message no longer gets clipped.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.8.0-alpha.2.exe` |
| Windows portable | `ToonTownMultiTool-Portable-v0.8.0-alpha.2.zip` |
| macOS | `ToonTownMultiTool-v0.8.0-alpha.2.dmg` |
| Linux AppImage | `ToonTownMultiTool-v0.8.0-alpha.2.AppImage` |
| Linux Flatpak | `ToonTownMultiTool-v0.8.0-alpha.2.flatpak` |
| Linux .deb | `ToonTownMultiTool-v0.8.0-alpha.2.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.8.0-alpha.2
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
