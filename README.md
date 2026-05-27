# 🎮 ToonTown MultiTool

A multitoon controller for **Toontown Rewritten** and **Corporate Clash** on Linux and Windows.

Built with Python and PySide6.

<!-- Hero screenshot goes here. Suggested: top-of-app multitoon tab with
     4 toons enabled, 1200x700 PNG. Drop the file into assets/ and add
     an img tag once available. -->

---

## Status: alpha (pre-1.0)

ToonTown MultiTool is in active alpha development. The architecture is
still changing as features land: wine input bridge for Corporate Clash,
Proton / Bottles / Lutris integration, keymap schema redesigns, launcher
and runtime redesigns. Expect occasional breaking changes between alpha
releases.

Releases prior to `v0.6.0-alpha.3` were retagged from `v1.x` / `v2.x` on
2026-05-27 to reflect the pre-1.0 status. See `CHANGELOG.md` for the full
mapping.

---

## ✨ Features

**Multitoon control**
- Broadcast keyboard input to up to 4 background toons simultaneously
- Per-toon movement key mapping (each toon can use a different key set: WASD or fully custom)
- Up to 8 custom key sets
- Per-toon keep-alive timer with configurable key and interval

**Game support**
- Toontown Rewritten: form-based login, queue polling, Flatpak launcher
- Corporate Clash: JSON API login, CLI credential injection

**Account management**
- Up to 16 TTR and CC accounts with OS keyring storage (Secret Service on Linux, Credential Locker on Windows)
- Passwords never written to disk, keyring only
- One-click launch with automatic credential injection

**Companion app integration (TTR)**
- Live toon names, laff points, and jellybean counts from the TTR Local API
- Toon portrait images via the Rendition API
- Works with multiple Flatpak TTR instances via XRes PID resolution

**Session profiles**
- 5 named profiles storing which toons are enabled
- Load profiles via hotkeys (Ctrl+1 through Ctrl+5)

**UI**
- Chip-rail navigation under the header (icon + label) with animated transitions
- Click the app logo in the header to open the Credits page
- Light and dark themes (auto-detected from system)

---

## 📥 Installation

Install on Windows (installer, portable ZIP, or source) or on Linux (Arch,
Flatpak, AppImage, .deb, or source). All paths run the same app from the
same release artifacts. The latest release is always at
`https://github.com/flossbud/ToonTown-MultiTool/releases/latest`.

### Windows

#### Installer (recommended)

Download `ToonTownMultiTool-Setup-vX.Y.Z-Windows-x86_64.exe` from the
[Releases page](https://github.com/flossbud/ToonTown-MultiTool/releases)
and run it. The wizard asks whether to install for just you (no admin
required) or for all users.

On first download, Windows SmartScreen will show "Windows protected your
PC". This is expected for unsigned installers, click "More info" then
"Run anyway".

#### Portable (no install)

If you'd rather not install, download
`ToonTownMultiTool-vX.Y.Z-Windows-x86_64.zip`. Extract it anywhere and run
`ToonTownMultiTool.exe` from the extracted folder. Same EXE, no Start Menu
entry or uninstaller.

#### Run from source

```powershell
git clone https://github.com/flossbud/ToonTown-MultiTool
cd ToonTown-MultiTool
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\venv\Scripts\Activate.ps1
python main.py
```

Pass `-Yes` to skip prompts. PySide6 wheels are self-contained on Windows,
so no separate Qt6 install is required.

#### Windows notes

- Input via Win32 `PostMessage`, no focus stealing
- Corporate Clash supported alongside TTR

### Linux

Pick whichever fits your distro.

#### Arch Linux (AUR)

Published as [`toontown-multitool`](https://aur.archlinux.org/packages/toontown-multitool):

```bash
yay -S toontown-multitool       # or: paru -S toontown-multitool
```

Manual build with `makepkg`:

```bash
git clone https://aur.archlinux.org/toontown-multitool.git
cd toontown-multitool
makepkg -si
```

After install, launch from the application menu or run `toontown-multitool`
(or the short alias `ttmt`) from a terminal.

#### Flatpak

Download the `.flatpak` bundle from the
[Releases page](https://github.com/flossbud/ToonTown-MultiTool/releases) and
install it:

```bash
flatpak install --user ./TTMultiTool-vX.Y.Z-Linux-x86_64.flatpak
flatpak run io.github.flossbud.ToonTownMultiTool
```

The Flatpak runs in a sandbox and uses `flatpak-spawn` to launch the host
TTR and Corporate Clash engines, so the games must already be installed on
the host.

#### AppImage

Download `TTMultiTool-vX.Y.Z-Linux-x86_64.AppImage` from the Releases page,
mark it executable, run it:

```bash
chmod +x TTMultiTool-vX.Y.Z-Linux-x86_64.AppImage
./TTMultiTool-vX.Y.Z-Linux-x86_64.AppImage
```

The AppImage is built against glibc 2.31, so it runs on any of the
supported distros below or newer. Double-click launch additionally needs
`libfuse2`; on newer distros that don't ship it (Ubuntu 24.04, Mint 22)
either install it (`sudo apt install libfuse2`) or run with
`--appimage-extract-and-run`.

#### Debian / Ubuntu / Mint (.deb)

Download `ttmultitool_X.Y.Z_amd64.deb` from the Releases page and install
it:

```bash
sudo apt install ./ttmultitool_X.Y.Z_amd64.deb
```

#### Run from source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool
cd ToonTown-MultiTool
./install.sh
source venv/bin/activate           # use activate.fish if your shell is fish
python main.py
```

`install.sh` detects your OS and distro, installs Python 3.9 to 3.14 if
missing, installs the Qt6 runtime libraries, creates a venv at `./venv`,
and installs the Python dependencies. It asks before each `sudo` command;
pass `--yes` to skip the prompts. Re-running is fast: it detects an
existing valid venv via a SHA-256 sentinel and exits without re-prompting
unless `requirements.txt` has changed or `--force` is passed.

For unsupported distros (openSUSE, Gentoo, NixOS) or if you've already
installed Python 3.9 to 3.14 and the Qt6 runtime libraries yourself, skip
the OS package detection:

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

Wayland is auto-detected since v0.3.0-alpha.3. On older releases under
Wayland, force xcb:

```bash
QT_QPA_PLATFORM=xcb python main.py
```

#### Linux notes

- Tested on Fedora (KDE Plasma, GNOME) with Wayland and X11
- KWallet and GNOME Keyring both supported
- Flatpak TTR instances fully supported via XRes PID resolution

---

## Configuration

Config files live at `~/.config/toontown_multitool/`:

| File             | Contents                          |
|------------------|-----------------------------------|
| `settings.json`  | App preferences                   |
| `accounts.json`  | Account metadata (no passwords)   |
| `keymaps.json`   | Custom movement key sets          |
| `profiles.json`  | Named session profiles            |

Passwords live only in the OS keyring (Secret Service on Linux, Credential
Locker on Windows), never in these files.

---

## Updates

The app can check for new releases at startup. Toggle it under **Settings >
Updates**, or click **Check now** any time. When a new release is found, a
banner appears at the top of the window; click it for release notes and the
choices Update now, Remind me later, or Skip this version.

What "Update now" does depends on how you installed:

| Install method      | Update action                                                |
|---------------------|--------------------------------------------------------------|
| Windows installer   | Downloads the new installer and prompts before running it    |
| AppImage            | Opens the release page in your browser                       |
| Flatpak, AUR, .deb  | Opens your default terminal with the right package-manager command (`flatpak update`, your AUR helper, or `dpkg -i` via `pkexec` for the new .deb) |
| Run from source     | Shows the `git pull` command in a copyable dialog            |

---

## Privacy

See [PRIVACY.md](PRIVACY.md) for what data ToonTown MultiTool stores on
your device, where, and what is sent to the official game servers when
you launch a toon. The app contains no telemetry, analytics, or crash
reporting.

---

## License

MIT. Free to use, share, and modify.

---

by **flossbud**
