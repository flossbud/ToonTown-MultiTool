## ToonTown MultiTool v2.1.1

Adds a per-toon discovery affordance for Keep-Alive, refreshes the Credits tab, plus a batch of Linux desktop integration fixes for GNOME / Wayland.

---

### New

- Each toon card now shows a small `?` help icon next to the chat button whenever Keep-Alive is disabled at the master level. Clicking it opens a short popover explaining what Keep-Alive does (and the TOS posture around it) with a "Go to Settings" shortcut that scrolls to and pulse-highlights the Keep-Alive group in Settings. The icon disappears as soon as Keep-Alive is enabled.
- Credits tab refreshed with new artwork and an updated description that reflects the app's full scope (both supported games, both supported platforms). The version number now updates automatically with each release.

---

### Bug Fixes

- Fixed the app hanging silently for several seconds before quitting on a fresh GNOME session, when the SecretService keyring was locked or hadn't been initialised yet. The diagnostic dump that triggered the hang now uses the same timed wrapper as the rest of the credential code, and runs after the keyring probe completes instead of before it.
- Fixed the app, when launched on Linux from a pinned dash icon (Arch/AUR install), opening as a separate generic-icon entry instead of grouping under the pinned launcher. The .desktop file installed system-wide now matches the reverse-DNS app id (`io.github.flossbud.ToonTownMultiTool`) that Qt sets as the Wayland app_id and as WM_CLASS on X11.
- Fixed "system" theme preference always picking light mode on GNOME, even when GNOME was set to prefer dark. The app now reads the desktop's `org.freedesktop.appearance.color-scheme` setting directly, with three independent fallback paths.
- The app now re-themes live when you toggle dark/light mode at the OS level — no restart required. Only applies when your in-app theme preference is "system"; explicit light/dark settings are not overridden.

---

### Internal

- Theme detection refactored into a small chain (Qt styleHints → xdg-desktop-portal direct query → palette inspection) with a 1 s memoisation cache invalidated by OS-level change notifications, so per-paint cost stays at zero without sacrificing live updates.
- AppDir desktop entry and icon basenames now match the reverse-DNS app id, so the AppImage build is consistent with the AUR and Flatpak builds.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.1.1-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.1.1-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.1.1-Windows-x86_64.zip` | Windows 10/11 |

Arch users: install via AUR (`yay -S toontown-multitool` or your preferred helper).

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package — it doesn't ship with the app.
