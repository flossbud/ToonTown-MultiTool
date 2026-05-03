# AUR Package Design: toontown-multitool

## Goal

Publish ToonTown MultiTool to the AUR as a source-based package so Arch Linux users can install it via `yay`, `paru`, or `makepkg`.

## Package Metadata

- **Name:** `toontown-multitool`
- **Version:** Tracks GitHub release tags (e.g. `2.0.1`)
- **License:** MIT
- **Source:** GitHub tarball from tagged release
- **Launch commands:** `toontown-multitool` (primary), `ttmt` (symlink)

## Architecture

Source-based install. No PyInstaller, no bundling. The PKGBUILD installs Python source files to `/usr/share/toontown-multitool/`, creates a launcher script, and declares Arch-packaged Python dependencies.

## Installed Files

| Path | Contents |
|------|----------|
| `/usr/share/toontown-multitool/` | All Python source (main.py, tabs/, utils/, services/) |
| `/usr/bin/toontown-multitool` | Launcher shell script |
| `/usr/bin/ttmt` | Symlink to `toontown-multitool` |
| `/usr/share/applications/toontown-multitool.desktop` | Desktop entry |
| `/usr/share/pixmaps/toontown-multitool.png` | App icon |

## Dependencies (Arch package names)

- `python` (>= 3.10)
- `python-pyside6`
- `python-pynput`
- `python-requests`
- `python-keyring`
- `python-certifi`
- `python-cryptography`
- `python-xlib`
- `python-secretstorage`
- `xdotool` (runtime, used for window detection)

## PKGBUILD

Lives in a separate AUR git repo (`aur/toontown-multitool`), not in the main project repo.

The PKGBUILD:
1. Downloads the source tarball for the tagged version from GitHub
2. Installs Python source files to `/usr/share/toontown-multitool/`
3. Installs the launcher script to `/usr/bin/toontown-multitool`
4. Creates `ttmt` symlink
5. Installs `.desktop` file and icon

## Launcher Script

```bash
#!/bin/bash
exec python /usr/share/toontown-multitool/main.py "$@"
```

## Desktop Entry

```ini
[Desktop Entry]
Name=ToonTown MultiTool
Exec=toontown-multitool
Icon=toontown-multitool
Type=Application
Categories=Game;
Comment=Multiboxing input control for Toontown
```

## Maintenance Workflow

1. Push a new tag to the main repo (e.g. `v2.0.2`)
2. Update `pkgver` in PKGBUILD
3. Update checksums (`updpkgsums`)
4. Regenerate `.SRCINFO` (`makepkg --printsrcinfo > .SRCINFO`)
5. Push to AUR repo

## Files to Add to Main Repo

A `.desktop` file suitable for system-wide install (the existing `AppDir/ToonTownMultiTool.desktop` is AppImage-specific). The icon (`ToonTownMultiTool.png`) can be reused as-is.
