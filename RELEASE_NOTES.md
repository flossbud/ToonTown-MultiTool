## ToonTown MultiTool v2.1.1

Adds a per-toon discovery affordance for Keep-Alive, refreshes the Credits tab, plus a batch of Linux desktop integration fixes for GNOME / Wayland.

---

### New

- Each toon card now shows a small `?` help icon next to the chat button when Keep-Alive is disabled, with a popover that explains the feature and offers a one-click jump to the Settings group.
- Credits tab refreshed with new artwork and an updated description.

---

### Bug Fixes

- Fixed the app hanging for several seconds on quit on a fresh GNOME session, when the SecretService keyring hadn't been initialised yet.
- Fixed the app opening as a separate generic-icon entry on Linux dash launchers (Arch/AUR install) instead of grouping under the pinned icon.
- Fixed "system" theme preference always picking light mode on GNOME, even when GNOME was set to prefer dark.
- Theme now updates live when you toggle dark/light mode at the OS level (no restart required), if your in-app theme is set to "system".

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.1.1-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.1.1-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.1.1-Windows-x86_64.zip` | Windows 10/11 |

Arch users: install via AUR (`yay -S toontown-multitool` or your preferred helper).

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package; it doesn't ship with the app.
