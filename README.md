<p align="center">
  <img src="assets/logos/ttmt_logo_icon+text.png" alt="ToonTown MultiTool" width="480">
</p>

A multitoon controller for **Toontown Rewritten** and **Corporate Clash** on Linux and Windows.

<!-- Hero screenshot goes here. Suggested: top-of-app multitoon tab with
     4 toons enabled, 1200x700 PNG. Drop the file into assets/ and add
     an img tag once available. -->

---

## Project Status

**ToonTown MultiTool is in active alpha development.** Features are still being added and some may change between alpha releases. Updates usually go smoothly: your saved accounts, profiles, and key layouts carry over.

The project has moved to a pre-1.0 alpha line to better reflect maturity.
Past releases v1.0 through v2.3.0-a1 have been retagged to v0.1.0-alpha.1 through v0.6.0-alpha.2. Releases will follow this structure moving forward.

---

## ✨ Features

### 🎮 Multitoon control
- Play up to 4 toons at the same time. What you do on the active toon (move, jump, talk, attack) happens on the others too.
- Each toon can use a different set of movement keys (WASD, arrow keys, or your own custom layout).
- Save up to 8 key layouts and assign a different one to each toon.
- Keep background toons from going idle: pick a key and an interval, and the app presses it for them automatically. **(The use of Keep-Alive and other automation tools is against TTR and CC ToS, and thus is disabled by default. Enable in settings at your own risk.)**
- Decide where your chat goes: four chat handling modes (Focused Toon Only, All Toons, Keyset Dynamic, Per-Toon (manual)), switchable under Settings > Features. Focused Toon Only is the default.
- Press F5 anywhere in the app to refresh the detected toon list.

### 🖱️ Click Sync
- Turn it on and your mouse plays every synced toon at once: clicks, drags, and hover movement mirror from the window you're playing into your other selected TTR windows, landing at the corresponding spot in each.
- Pick which toons join with the click sync button on each toon card, then flip the master switch in Settings > Features. Works when the windows share proportions. Off by default.
- Each synced window shows that toon's own glove cursor where the mirrored mouse lands, and never on the window you're actively using. On by default; toggle it in the same settings card.

### <img src="assets/ttr.png" height="22"> Toontown Rewritten support
- Sign in to TTR from inside the app. If TTR has a login queue, you see your queue position and ETA.
- Launches both the standard TTR install and the official Flatpak version.
- See each toon's name, laff, jellybean count, and portrait update live while you play, across all your open TTR windows.

### <img src="assets/cc.png" height="22"> Corporate Clash support
- Sign in to CC from inside the app.
- Plays nicely with however you have CC installed: native Windows, or any major Linux setup (Wine, Bottles, Lutris, Steam Proton, and similar).
- Multi-toon for CC, which CC's official launcher doesn't support out of the box.
- If CC reports the wrong species for one of your toons and the portrait shows the wrong character, set the right one per-toon and it sticks.

### 🔑 Accounts
- Save up to 16 accounts across both games, with one-click launch.
- Passwords are stored securely; the app never writes them into plain files. See [PRIVACY.md](PRIVACY.md) for details.

### 💾 Session profiles
- Save up to 5 named setups (which toons are active, plus their movement keys and anti-idle settings).
- Switch setups instantly with Ctrl+1 through Ctrl+5.

---

## 📥 Installation

Install on Windows (installer, portable ZIP, or source) or on Linux (Arch, Flatpak, AppImage, .deb, or source). The latest release is always at `https://github.com/flossbud/ToonTown-MultiTool/releases/latest`.

### Windows

#### Installer (recommended)

Download `ToonTownMultiTool-Setup-vX.Y.Z.exe` from the [Releases page](https://github.com/flossbud/ToonTown-MultiTool/releases) and run it. The wizard asks whether to install for just you (no admin needed) or for all users.

On first download, Windows SmartScreen will show "Windows protected your PC". This is expected for unsigned installers, click "More info" then "Run anyway".

#### Portable (no install)

Download `ToonTownMultiTool-Portable-vX.Y.Z.zip`, extract anywhere, and run `ToonTownMultiTool.exe` from the extracted folder. No Start Menu entry, no uninstaller.

#### Run from source

```powershell
git clone https://github.com/flossbud/ToonTown-MultiTool
cd ToonTown-MultiTool
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\venv\Scripts\Activate.ps1
python main.py
```

Pass `-Yes` to skip prompts.

### Linux

Pick whichever fits your distro.

#### Arch Linux (AUR)

Published as [`toontown-multitool`](https://aur.archlinux.org/packages/toontown-multitool):

```bash
yay -S toontown-multitool       # or: paru -S toontown-multitool
```

After install, launch from your application menu or run `toontown-multitool` (short alias `ttmt`) from a terminal.

#### Flatpak

Download the `.flatpak` from the [Releases page](https://github.com/flossbud/ToonTown-MultiTool/releases):

```bash
flatpak install --user ./ToonTownMultiTool-vX.Y.Z.flatpak
flatpak run io.github.flossbud.ToonTownMultiTool
```

You need TTR or CC already installed on your system; the Flatpak doesn't bundle the games.

#### AppImage

```bash
chmod +x ToonTownMultiTool-vX.Y.Z.AppImage
./ToonTownMultiTool-vX.Y.Z.AppImage
```

If double-clicking does nothing on Ubuntu 24.04 or Mint 22, either install `libfuse2` (`sudo apt install libfuse2`) or run with `--appimage-extract-and-run`.

#### Debian / Ubuntu / Mint (.deb)

```bash
sudo apt install ./ToonTownMultiTool-vX.Y.Z.deb
```

#### Run from source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool
cd ToonTown-MultiTool
./install.sh
source venv/bin/activate           # use activate.fish if your shell is fish
python main.py
```

`install.sh` detects your distro, installs Python 3.9 to 3.14 and the Qt6 runtime libraries if missing, and sets up a local Python environment. It asks before each `sudo` command; pass `--yes` to skip the prompts.

For unsupported distros (openSUSE, Gentoo, NixOS), or if you already have Python 3.9 to 3.14 and Qt6 installed:

```bash
./install.sh --skip-system-deps
```

#### Supported distros

**CI-tested on every push:**
- Debian 11 (Python 3.9)
- Debian 12 (Python 3.11)
- Ubuntu 22.04 LTS (Python 3.10)
- Ubuntu 24.04 LTS (Python 3.12)
- Fedora latest (Python 3.14)
- Arch Linux rolling (Python 3.14)

**Also supported (inherits parent base):**
- LMDE 5 (= Debian 11)
- LMDE 6 (= Debian 12)
- Linux Mint 21.x (= Ubuntu 22.04)
- Linux Mint 22.x (= Ubuntu 24.04)

#### Wayland

By default the app runs through XWayland (xcb) on Wayland sessions; this is what the multitoon input features need. Set `TTMT_USE_WAYLAND=1` to opt into native Wayland instead (multitoon input features won't work there).

---

## Configuration

Your settings, profiles, and account list live in `C:\Users\<username>\.config\toontown_multitool\` (Windows) or `~/.config/toontown_multitool/` (Linux). Back it up, copy it between machines, or delete it to start fresh.

See [PRIVACY.md](PRIVACY.md) for the full breakdown of what's stored on your device and what gets sent to the game servers.

---

## Updates

The app can check for new releases at startup. Toggle it under **Settings > Updates**, or click **Check now** any time. When a new release is found, a banner appears at the top of the window. Click it to read the release notes and choose Update now, Remind me later, or Skip this version.

The update action depends on how you installed:

| Install method      | What "Update now" does                                          |
|---------------------|-----------------------------------------------------------------|
| Windows installer   | Downloads the new installer and prompts before running it       |
| AppImage            | Opens the release page in your browser                          |
| Flatpak, AUR, .deb  | Opens a terminal with the right update command for your install |
| Run from source     | Shows a copyable `git pull` command                             |

---

## Troubleshooting

### Windows: background toons will not move together

If you can move one toon but the others do not follow, your game is probably
running as administrator while ToonTown MultiTool is not. Windows blocks a normal
program from sending input to a program that has administrator access. MultiTool
will offer to restart with administrator access so it can control every toon. You
can also fix this by starting the game without administrator access.

---

## Privacy

See [PRIVACY.md](PRIVACY.md) for what data ToonTown MultiTool stores on your device, where, and what is sent to the official game servers when you launch a toon. The app contains no telemetry, analytics, or crash reporting.

---

## License

MIT. Free to use, share, and modify.

---

Releases prior to `v0.6.0-alpha.3` were retagged from `v1.x` / `v2.x` on 2026-05-27 to reflect the pre-1.0 status. See `CHANGELOG.md` for the mapping.

by **flossbud**
