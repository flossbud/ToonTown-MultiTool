# 🎮 ToonTown MultiTool

A multitoon controller for **Toontown Rewritten** and **Corporate Clash** on Linux and Windows.

Built with Python + PySide6.

---

## ✨ What's New in v2.0

**🪟 Windows Support**
- v2.0 adds full Windows support

**⌨️ Custom Movement Key Sets**
- v2.0 lets each slot use a different key set, and reads the default configuration for input translation
- Up to 8 named key sets, fully customisable in the new Keymap tab
  
**🐾 TTR Companion App Integration**
- Live toon name, laff, and jellybean count per slot in the Multitoon tab
- Toon portrait images fetched and cached from the Rendition API

**💾 Session Profiles**
- 5 named profiles storing which toon slots are active
- Load via Ctrl+1–5 hotkeys or change via icons on the main tab, replacing the old Preset system

**⚡ Input Backend**
- Keystrokes now sent via Xlib `send_event` directly; no more `xdotool` subprocess per keypress, fixing GNOME Wayland portal auth prompts

**🔐 Account Manager**
- Store up to 16 TTR and CC accounts with one-click launch
- Passwords stored exclusively in the OS keyring, never written to disk
- Handles TTR login queues and 2FA automatically

**🎮 Corporate Clash Support**
- Launch, log in to, and multibox CC alongside TTR
- The app automatically identifies which game each window belongs to

---

## 🕹️ Features

**Multitoon Control**
- Broadcast keyboard input to up to 4 background toons simultaneously
- Per-toon movement key mapping! Each toon can use a different key set (WASD or fully custom)
- Up to 8 custom key sets
- Per-toon keep-alive timer with configurable key and interval

**Game Support**
- Toontown Rewritten: form-based login, queue polling, Flatpak Launcher
- Corporate Clash: JSON API login, CLI credential injection
  
**Account Management**
- Store up to 16 TTR and CC accounts with secure OS keyring storage (Secret Service on Linux, Credential Locker on Windows)
- Passwords never written to disk - keyring only
- One-click launch with automatic credential injection

**Companion App Integration (TTR)**
- Displays toon names, laff points, and jellybean counts live from the TTR Local API
- Toon portrait images via the Rendition API
- Works correctly with multiple Flatpak TTR instances using XRes PID resolution

**Session Profiles**
- 5 named profiles storing which toons are enabled
- Load profiles via hotkeys (Ctrl+1 through Ctrl+5)

**UI**
- Chip-rail navigation under the header (icon + label) with animated transitions
- Click the app logo in the header to open the Credits page
- Light and dark themes (auto-detects from system)

---

## ⚙️ Requirements

**🐧 Linux:**
- Python 3.9 to 3.13
- PySide6, pynput, python-xlib
- `xdotool` (window detection only, not required for input)
- Secret Service-compatible keyring (GNOME Keyring or KWallet)

**🪟 Windows:**
- Python 3.9 to 3.13
- PySide6, pynput, pywin32

---

## Installation

### Supported Linux distributions

The AppImage, Flatpak, and run-from-source paths are CI-tested on every push against:

| Base distro          | Python | Linux Mint equivalent |
|----------------------|--------|-----------------------|
| Debian 11 (bullseye) | 3.9    | LMDE 5-era            |
| Debian 12 (bookworm) | 3.11   | LMDE 6                |
| Ubuntu 22.04 LTS     | 3.10   | Mint 21.x             |
| Ubuntu 24.04 LTS     | 3.12   | Mint 22.x             |

The AppImage is built against glibc 2.31, so it runs on any of the above and newer. Like
every Linux GUI application, it relies on the host's standard graphics stack (libGL/libEGL/
libxcb), present on every desktop install. AppImage double-click launch additionally needs
`libfuse2`; on newer distros that don't ship it (Ubuntu 24.04, Mint 22) either install it
(`sudo apt install libfuse2`) or run the AppImage with `--appimage-extract-and-run`.

### Arch Linux (AUR)

The package is published as [`toontown-multitool`](https://aur.archlinux.org/packages/toontown-multitool) on the AUR.

Using `yay`:
```bash
yay -S toontown-multitool
```

Using `paru`:
```bash
paru -S toontown-multitool
```

Manual build with `makepkg`:
```bash
git clone https://aur.archlinux.org/toontown-multitool.git
cd toontown-multitool
makepkg -si
```

After installation, launch from your application menu, or from a terminal with `toontown-multitool` (or the short alias `ttmt`).

### Linux (Flatpak)

A `.flatpak` bundle is attached to each release on the [Releases page](https://github.com/flossbud/ToonTown-MultiTool/releases). Download the file ending in `.flatpak` and install it:

```bash
flatpak install --user ./TTMultiTool-vX.Y.Z-Linux-x86_64.flatpak
flatpak run io.github.flossbud.ToonTownMultiTool
```

The Flatpak runs the app in a sandbox and uses `flatpak-spawn` to launch the host TTR and Corporate Clash engines, so you must already have those games installed on the host.

### Windows

**Recommended:** Download the installer from the
[latest release](https://github.com/flossbud/ToonTownMultiTool-v2/releases/latest):

- `ToonTownMultiTool-Setup-vX.Y.Z-Windows-x86_64.exe`

Run the installer. You'll see a standard wizard that asks whether to install
for just you (recommended, no admin required) or for all users on the PC.

On first download, Windows SmartScreen will show "Windows protected your PC".
This is expected for unsigned installers. Click "More info" then "Run anyway".

**Portable (no install):** If you'd rather not install, download the ZIP:

- `ToonTownMultiTool-vX.Y.Z-Windows-x86_64.zip`

Extract it anywhere and run `ToonTownMultiTool.exe` from inside the extracted
folder. Same EXE, no Start Menu entry or uninstaller.

**Beta channel:** Builds from the development branch are released as separate
prereleases:

- `ToonTownMultiTool-Setup-vX.Y.Z-A-Windows-x86_64.exe`

The beta installer installs side-by-side with the stable version under a
separate Start Menu folder, so testing a beta won't disturb your working install.

### Run from source

After extracting or cloning the source, from inside the repo directory:

**Linux** (Debian/Ubuntu/Mint, Fedora, Arch):

```bash
./install.sh
source venv/bin/activate           # use activate.fish if your shell is fish
python main.py
```

**Windows:**

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\venv\Scripts\Activate.ps1
python main.py
```

The installer detects your OS and distro, installs Python 3.9 to 3.13 if missing, installs the Qt6 runtime libraries on Linux (PySide6 wheels are self-contained on Windows), creates a venv at `./venv`, and installs the Python dependencies. It will ask before each `sudo` command; pass `--yes` (or `-Yes` on Windows) to skip the prompts. Re-running the installer is fast: it detects an existing valid venv via a SHA-256 sentinel and exits without re-prompting unless `requirements.txt` has changed or `--force` is passed.

For unsupported distros (openSUSE, Gentoo, NixOS, etc.) or if you've already installed Python 3.9 to 3.13 and the Qt6 runtime libraries yourself, skip the OS package detection and go straight to the venv + pip install:

```bash
./install.sh --skip-system-deps
```

### Linux: Wayland sessions

Wayland is auto-detected in v2.0.2 and later. If you are running an older release on Wayland and hit input issues, force xcb:

```bash
QT_QPA_PLATFORM=xcb python main.py
```

---

## Platform Notes

### Linux
- Tested on Fedora (KDE Plasma, GNOME) with Wayland and X11
- Flatpak TTR instances fully supported via XRes PID resolution
- KWallet and GNOME Keyring both supported

### Windows
- Input via Win32 `PostMessage`, no focus stealing
- Corporate Clash supported alongside TTR

---

## Configuration

Config files at `~/.config/toontown_multitool/`:

| File | Contents |
|------|----------|
| `settings.json` | App preferences |
| `accounts.json` | Account metadata (no passwords) |
| `keymaps.json` | Custom movement key sets |
| `profiles.json` | Named session profiles |

---

## Updates

The app can check for new releases on GitHub at startup. Toggle this
under Settings, Updates, or click "Check now" any time. When an update
is found, a banner appears at the top of the window; click it for
release notes and choices (Update now, Remind me later, Skip this
version).

The update action depends on how you installed:

- **Windows**: downloads the new installer and prompts before running it.
- **AppImage**: opens the release page in your browser.
- **Flatpak, AUR, .deb**: opens your default terminal with the right
  package-manager command (Flatpak update, your AUR helper, or `dpkg -i`
  via pkexec on the new .deb).
- **Source**: shows the `git pull` command in a copyable dialog.

## Privacy

See [PRIVACY.md](PRIVACY.md) for what data TTMultiTool stores on your device, where, and what is sent to the official game servers when you launch a toon. The app contains no telemetry, analytics, or crash reporting.

## License

MIT License. Free to use, share, and modify.

---

## Author

Made by **flossbud**
