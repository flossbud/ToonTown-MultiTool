## ToonTown MultiTool v0.7.0-alpha.4

Adds Click Sync: Mouse Input Forwarding

---

### Improvements

- New Click Sync feature: mirror mouse clicks, drags, and hover movement from the window you're playing to your other selected toons. Choose toons with the click sync button on each toon card; works on Windows and Linux when the windows have matching proportions. Off by default.
- Ghost cursors: each synced toon shows its own glove cursor where the mirrored mouse lands, and never on the window you're actively using. Toggle it under Settings > Features.
- Click Sync has its own card under Settings > Features, alongside Keep-Alive and Chat Handling.
- A synced toon whose window closes now drops out of the sync group automatically; click its button again after relaunching to rejoin.
- Running from source no longer shows an update banner when your checkout is already at or past the latest release.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.7.0-alpha.4.exe` |
| Windows portable | `ToonTownMultiTool-Portable-v0.7.0-alpha.4.zip` |
| Linux AppImage | `ToonTownMultiTool-v0.7.0-alpha.4.AppImage` |
| Linux Flatpak | `ToonTownMultiTool-v0.7.0-alpha.4.flatpak` |
| Linux .deb | `ToonTownMultiTool-v0.7.0-alpha.4.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.7.0-alpha.4
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
