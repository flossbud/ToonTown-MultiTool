## ToonTown MultiTool v0.7.0-alpha.1

Adds multi-account pagination and reordering, a custom window frame, and more reliable multi-toon input.

---

### Improvements

- Store up to 16 accounts per game, shown four per page with a pager, and reorder them by dragging or using arrow buttons in a new edit modal (with a smooth swap animation).
- New custom window frame: a rounded translucent card with classic traffic-light controls and a centered logo banner. A new "Use system title bar" setting keeps the native frame if you prefer it.
- A new app logo, shown in the window header.
- New "Strict keyset separation (TTR)" setting, on by default, keeps each TTR window's movement keys isolated regardless of which window is focused.
- Keep-Alive now holds a real system sleep inhibitor so your computer will not sleep mid-session, and shows a clear message if it cannot.
- Redesigned in-app update banner.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.7.0-alpha.1-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.7.0-alpha.1-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.7.0-alpha.1-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.7.0-alpha.1-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.7.0-alpha.1-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.7.0-alpha.1
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
