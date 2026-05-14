## ToonTown MultiTool v2.2.0

Minor release focused on input forwarding (full keyboard coverage on Windows
and Linux), Windows process detachment for launched games, and automatic TTR
settings detection at startup. Also includes credits/UI fixes and a footer-link
fix for the AppImage build.

---

### Bug Fixes

- **Launched games now survive closing ToonTown MultiTool on Windows.** Previously, when TTMT exited, all child game processes were killed along with it because Windows put them in the same Job Object. The launcher now explicitly detaches each launched game from the multitool's job, so quitting TTMT no longer terminates your active toon windows.
- **TTR settings auto-detect is more resilient at startup.** If `settings.json` is briefly unreadable on launch (e.g., TTR is mid-write), TTMT now falls back to the last successfully detected keymap rather than treating it as a fresh install.
- **Arrow-key movement now forwards correctly to background toons on Windows.** Multitoon forwarding was completely broken when TTR was configured with default arrow-key movement. The Win32 input backend now sets the extended-key bit in PostMessage `lparam` for arrow keys, which Panda3D requires to distinguish them from numpad arrows.
- **Right Ctrl, Right Alt, and the navigation cluster (Insert/Delete/Home/End/PageUp/PageDown) now forward correctly on Windows.** Same root cause as arrow-key forwarding; same fix.
- **Function keys (F1-F12) now forward correctly to Windows TTR.** Win32, hotkey detection, and keymap translation paths now all recognize the full key vocabulary.
- **Left Ctrl now posts the same generic key code that Right Ctrl does on Windows,** so modifier-combined hotkeys behave consistently regardless of which Ctrl is used.
- **Credits page portrait now renders on the Arch AUR `ttmt-beta` build.** The asset shipped fine, but Arch's `pyside6` package doesn't include the Qt WebP image plugin, so the portrait silently failed to load. The asset is now PNG and has zero plugin dependencies.
- **Credits page now follows OS light/dark toggles when your TTMT theme is set to `system`.** Previously only the rest of the app would repaint when the OS toggled themes.
- **Launch tab button no longer reverts to "Launch" while the status dot stays green.** A card rebuild after launch (triggered by adding/editing/deleting another account, or changing max-accounts-per-game) was resetting the button text without consulting the underlying launcher state. The button now stays in sync with the running launcher across all rebuild paths.
- **Footer links in the AppImage build now open correctly.** Previously the Credits tab footer links wouldn't open in the AppImage-packaged build.

---

### Improvements

- **TTR settings auto-detect at startup.** TTMT now reads your TTR `settings.json` on launch and applies the detected control bindings to the default keyset (Set 1) without requiring you to press the manual "Detect" button each session. Detection covers Linux native, Linux Flatpak, and Windows (`%APPDATA%\Toontown Rewritten`); the result is persisted via the app's settings store so it survives runs where `settings.json` is briefly unreadable.
- **TTR install location is now auto-detected as a fallback.** If TTMT's configured engine directory is missing, the app probes standard install paths so launches keep working without manual reconfiguration.
- **Chat-aware key blocking.** When you turn chat OFF for a background toon, TTMT now blocks the right keys for your TTR config: Return and Escape always, plus a-z if your TTR install has "open chat by typing" enabled (which is the default when no hotkey is bound to a letter). This fixes a long-standing case where chat would silently reopen on background toons in default TTR configurations because TTMT was only blocking Return.
- **Hotkey detection on Linux recognizes the full keyboard vocabulary** (arrow keys, the nav cluster, and F1-F12) for both binding and triggering.
- **Keymap tab understands TTR's full settings vocabulary** (`arrow_*`, `home`, `end`, `page_up`, `page_down`, `f1`-`f12`) so detected bindings populate correctly from `settings.json`.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.2.0-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.2.0-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.2.0-Windows-x86_64.zip` | Windows 10/11 |

Arch users: install via AUR (`yay -S toontown-multitool` or your preferred helper).

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package; it doesn't ship with the app.
