## ToonTown MultiTool v2.2.0

Minor release fixing critical Windows input bugs, adding TTR settings auto-detection, and tightening chat-aware key blocking. Originally planned as a `2.1.3-a` private smoke iteration; bumped to `2.2.0` once the structural scope (new TTR-settings helper, new injectable chat-block-list contract on InputService, Win32 backend behavioral fix) crossed into minor-bump territory.

---

### Bug Fixes

- **Arrow-key movement now forwards correctly to background toons on Windows.** Multitoon forwarding was completely broken when TTR was configured with default arrow-key movement. The Win32 input backend now sets the extended-key bit in PostMessage `lparam` for arrow keys, which Panda3D requires to distinguish them from numpad arrows.
- **Right Ctrl, Right Alt, and the navigation cluster (Insert/Delete/Home/End/PageUp/PageDown) now forward correctly on Windows.** Same root cause as arrow-key forwarding; same fix. Note: Left Ctrl is not a Win32 extended key per spec — if Left Ctrl as a hotkey is still misbehaving on your Windows install after this update, that's a separate issue.
- **Credits page portrait now renders on the Arch AUR `ttmt-beta` build.** The asset shipped fine, but Arch's `pyside6` package doesn't include the Qt WebP image plugin, so the portrait silently failed to load. The asset is now PNG and has zero plugin dependencies.
- **Credits page now follows OS light/dark toggles when your TTMT theme is set to `system`.** Previously only the rest of the app would repaint when the OS toggled themes.
- **Launch tab button no longer reverts to "Launch" while the status dot stays green.** A card rebuild after launch (triggered by adding/editing/deleting another account, or changing max-accounts-per-game) was resetting the button text without consulting the underlying launcher state. The button now stays in sync with the running launcher across all rebuild paths.

---

### Improvements

- **TTR settings auto-detect at startup.** TTMT now reads your TTR `settings.json` on launch and applies the detected control bindings to the default keyset (Set 1) without requiring you to press the manual "Detect" button each session. Detection covers Linux native, Linux Flatpak, and Windows (`%APPDATA%\Toontown Rewritten`); the result is persisted via the app's settings store so it survives runs where `settings.json` is briefly unreadable.
- **Chat-aware key blocking.** When you turn chat OFF for a background toon, TTMT now blocks the right keys for your TTR config: Return and Escape always, plus a–z if your TTR install has "open chat by typing" enabled (which is the default when no hotkey is bound to a letter). This fixes a long-standing case where chat would silently reopen on background toons in default TTR configurations because TTMT was only blocking Return.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.2.0-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.2.0-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.2.0-Windows-x86_64.zip` | Windows 10/11 |

Beta-channel Arch users: `paru -Syu` (or your preferred helper) to pick up the new `ttmt-beta` package.

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package; it doesn't ship with the app.
