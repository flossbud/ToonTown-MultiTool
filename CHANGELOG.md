# ToonTown MultiTool — Changelog

## v2.2 — Scope Refinement

### Removed: Invasion Tracker

The Invasions tab has been removed. Live cog invasion tracking will return in a dedicated companion app rather than living inside MultiTool.

This change sharpens MultiTool's scope around its core purpose: a multi-account input controller for Toontown Rewritten and Corporate Clash. Features that don't serve that purpose, however useful, belong in their own tools where they can be developed and shipped on their own cadence.

### Reworked: Navigation

The left sidebar has been replaced with a horizontal "chip rail" beneath the header. Four nav chips (Multitoon, Launch, Keymap, Settings) sit on the left; the Hints toggle and a debug-gated overflow menu live on the right. The app logo is now a clickable link to the Credits page.

The full-UI breakpoint shifts from 1280×800 to 1280×852 to keep the multitoon 2×2 card grid's content budget unchanged. The default-window compact layout was tightened slightly to fit the new ~52 px of chrome without compressing the controls pill.

### UI polish (post-chip-rail audit)

- Keyboard focus rings on chip-rail buttons and the hint toggle
- Light-mode slot-badge contrast bumped to clear WCAG 1.4.11
- Disabled Enable buttons now read as disabled (lower-contrast tokens)
- Header carries a live session status (Idle/Running + active toon count)
- "PROFILE" label above the profile-presets pill row
- Removed the divider between chips and the hint toggle
- Selected chip's accent border softened to honor the original soft-ring design intent
- Service-idle status text uses the theme's idle color (no longer italic/washed-out)
- Full-UI empty cards link out to the Launch tab via "Launch a game"
- Regression-pinned: light-mode full-UI cards keep their light theme on layout swap

---

## v2.0 — Complete Rewrite

v2.0 is a ground-up rewrite. The core concept is the same — multiboxing input control for Toontown — but almost every part of the app has been rebuilt or replaced.

---

### New: Corporate Clash Support

CC can now be launched, logged in to, and multiboxed alongside TTR. The app auto-detects which game each window belongs to and handles them separately throughout.

---

### New: Account Manager & Secure Login

Accounts (up to 16, across TTR and CC) are stored with labels and usernames in a config file. Passwords live exclusively in the OS keyring — GNOME Keyring or KWallet on Linux, Windows Credential Locker on Windows. Nothing is written to disk in plaintext.

One-click launch from the Launch tab handles login automatically, including TTR queue waiting and 2FA prompts.

Previously, there was no credential storage. You had to log in to each instance manually.

---

### New: TTR Companion App Integration

When TTR's local API is running, the Multitoon tab shows each toon's name, laff points, and jellybean count in real time. Toon portrait images are fetched from the Rendition API and cached.

This works correctly with multiple Flatpak instances — each window is matched to its API port using the XRes X11 extension rather than broken namespace PID lookups.

---

### New: Custom Movement Key Sets

v1.5.1 assumed every toon used WASD. v2.0 introduces a Keymap tab where you can define up to 8 named key sets and assign one per toon slot. The default sets are WASD and Arrow Keys; additional sets can be fully customised.

---

### New: Invasion Tracker

A live invasion tracker now sits in the sidebar, polling the TTR public API every 60 seconds and displaying active cog invasions by department with color coding.

Previously, invasion alerts existed as a background system but had no dedicated display.

---

### New: Session Profiles

Profiles replace the old Preset system. You can save 5 named profiles, each storing which toon slots are enabled. Profiles load instantly via Ctrl+1–5 hotkeys or the profile selector in the Multitoon tab.

---

### New: Windows Support

v1.5.1 was Linux-only. v2.0 adds a Win32 input backend that sends keystrokes to background game windows using `PostMessage` — no focus stealing. Window detection and credential storage also work natively on Windows.

---

### Changed: Input Backend

The Xlib backend now sends keystrokes directly from within the app process using `send_event`. Previously, each keystroke spawned an `xdotool` subprocess, which triggered GNOME's RemoteDesktop portal auth dialog on Wayland sessions. The new backend avoids that entirely.

`xdotool` is still used for window detection, but is no longer required for input.

---

### Changed: Navigation

The flat tab bar has been replaced with a sidebar. Navigation animates between panels with a fade transition. The debug/logs panel is hidden by default and toggled from Settings.

---

### Changed: Keep-Alive

Keep-alive is now configured per toon slot in the Multitoon tab rather than as a global setting in the Extras tab. The Extras tab now only contains a quick-launch button for TTR.

---

### Removed

- The Extras tab keep-alive controls (moved into Multitoon tab)
- The old Presets system (replaced by Profiles)
- Hardcoded WASD assumption
