## ToonTown MultiTool v2.1.3

Patch release introducing the ttmt-beta AUR channel and fixing AppImage footer links.

---

### Bug Fixes

- Footer links in the Credits tab now open in your browser when running the AppImage build.

---

### Improvements

- New beta channel: install `ttmt-beta` from AUR for pre-release smoke-test builds. Coexists alongside the stable `toontown-multitool` install with a separate icon, desktop entry, and config directory. Stable users see no change.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.1.3-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.1.3-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.1.3-Windows-x86_64.zip` | Windows 10/11 |

Arch users: install via AUR (`yay -S toontown-multitool` or your preferred helper).

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package; it doesn't ship with the app.
