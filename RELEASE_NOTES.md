## ToonTown MultiTool v0.8.0-alpha.1

Adds macOS support, a new Float UI overlay, global hotkeys, and a redesigned interface.

---

### New Features

#### macOS Support

- ToonTown MultiTool now runs on macOS. Install it by dragging the app out of the DMG into Applications. Apple has not notarized the app yet, so the first launch may prompt you to approve in Privacy & Security.
- The first run walks you through granting the two permissions the synced input features need. You can reopen that guide any time from Settings > macOS > Permissions.
- Your saved account passwords are protected behind the OS Keyring. Accessing accounts is gated by Touch ID, falling back to your login password. See PRIVACY.md for what is stored and where.
- All features (Keepalive, Click-Sync, Float UI) are fully supported.

#### Float UI

- Your toon cards lift out of the main window and float above the games as a click-through overlay, so the app won't block your gameplay.
- Click the emblem for a radial menu with Accounts, Home, Settings, plus a ring of recent accounts you can launch without leaving the overlay.
- Hide and show the toon cards from the radial menu.

#### Global Hotkeys

- Trigger MultiTool actions while a game holds focus, without switching windows.
- Assign single keys or up to three-key chords under Settings > Hotkeys.
- Hotkeys can launch accounts, manage the input service, apply individual settings and more.

---

### Improvements

- Settings has been rebuilt around color-coded category pills: General, Games, Keysets, Features, and Advanced.
- Keysets moved into Settings and is no longer a top-level tab. When both games are installed you pick the game first.
- Keysets now draws your layout as a keyboard. Click a row to spotlight its key, or click a keycap to rebind it.
- The tab bar is now Launcher, Multitoon, and Settings, with a new glass dock switcher.
- The Launcher has a redesigned account tile, pager, and reorder dialog.
- On the Launch Tab, you can assign a "Primary Toon" to your account, which acts as its header.
- Each account in the Launcher now shows its primary toon as a real portrait, so you can tell your accounts apart at a glance.
- The same portraits appear in the Float UI radial menu's accounts ring.
- Toon cards now fade to a dimmed state when a toon is turned off or its game window is not running, so your live toons stand out.
- The Keep-Alive interval no longer offers 10 minutes, due to this far exceeding the auto-logoff period. The longest interval is now 5 minutes.

---

### Bug Fixes

- Keep-Alive now presses the key your game client actually has bound. It was pressing the key from the toon's key set instead, which could send the wrong key entirely.
- Miscellaneous keys (ctrl, alt, esc) now reach your key layout on Windows instead of being dropped.
- On Windows, every key bound in your keymap is now suppressed properly. Bound keys outside of WASD and the arrows used to leak into the foreground game and could not drive the focused toon.
- A movement key no longer stays held after you switch a toon's key set while that key is down.
- After you send a chat message your background toons respond immediately. They were sluggish for about a second and a half, sometimes indefinitely or until a service restart.
- Ghost cursors no longer stutter during fast mouse movement.
- Ghost cursors now land in the right spot on scaled and high-DPI displays, such as a Windows laptop with display scaling on.
- On Windows, a ghost cursor moving behind another window is now clipped by it rather than disappearing entirely.
- Discarding portrait edits no longer leaves your color, pattern, zoom, and rotation changes applied for the rest of the session.
- Portrait pose tiles stay selectable while they load, and show a failure mark immediately instead of waiting out an eight second timeout.
- Portrait framing sliders now match the image you restored.
- Toon name labels no longer make the cards judder when the list refreshes.
- Toon cards keep a consistent height no matter what data a toon has, so their contents no longer get clipped.
- The app repaints less while a page is hidden, which lowers idle CPU use.
- Toon portraits no longer fail to load silently in the packaged builds. The pose downloader now ships with the certificate list it needs.
- The AppImage now runs through XWayland on Wayland sessions. It was forcing native Wayland, which silently broke input forwarding.
- The in-app updater no longer goes quiet once a release line passes its ninth alpha.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.8.0-alpha.1.exe` |
| Windows portable | `ToonTownMultiTool-Portable-v0.8.0-alpha.1.zip` |
| macOS | `ToonTownMultiTool-v0.8.0-alpha.1.dmg` |
| Linux AppImage | `ToonTownMultiTool-v0.8.0-alpha.1.AppImage` |
| Linux Flatpak | `ToonTownMultiTool-v0.8.0-alpha.1.flatpak` |
| Linux .deb | `ToonTownMultiTool-v0.8.0-alpha.1.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.8.0-alpha.1
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
