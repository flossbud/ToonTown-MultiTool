## ToonTown MultiTool v2.3.0-a

First alpha of the v2.3.0 cycle. This iteration ships the dev-branch
UI/UX rework that's been accumulating since v2.2.0 — new chip-rail
navigation, modern auto-hide scrollbars, a redesigned Settings tab,
and a motion system with reduce-motion controls — alongside a Corporate
Clash launch-diagnostic fix prompted by a user bug report.

Smoke-test this build before promotion to beta or stable. See
`SMOKETEST.md` attached to this Pre-release.

---

### Bug Fixes

- **Corporate Clash launch failures now report why in the in-app log.**
  Previously, when a CC login or game launch failed (network error,
  server rejection, untrusted engine path, etc.), the only visible
  feedback was a red status dot and a status-chip message — the actual
  error string never reached the log shown in the Debug tab, leaving
  users to file bug reports that didn't include the reason. Both
  `login_failed` and `launch_failed` paths now log their message so
  the next bug report includes the cause.

---

### Improvements

#### Windows installer
- Windows: new traditional installer wizard alongside the existing ZIP. The installer asks per-user or all-users scope, offers a desktop shortcut, lets you opt into Keep-Alive (with TOS warning) and "check for updates at startup", and registers in Add/Remove Programs. Beta and stable installs sit side-by-side. ZIP stays available for portable use.

#### Chip-rail navigation
- **The left sidebar is gone.** Navigation moved to a horizontal chip
  rail at the bottom of the window. Tabs (now named Launcher / Keysets
  / Multi-Toon) are rendered as text-under-icon chips with hover/press
  animations, focus rings, and a sliding pill indicator that tracks
  the selected chip.
- Page transitions use a horizontal push-slide animation between
  chips, vertical push-slide from the brand area to Credits.
- Brand area (icon + version pill) is clickable and opens the Credits
  page.
- Hint toggle relocated from the chip rail to the header strip.
- Hidden tabs accessible via an animated overflow popup (debug-gated).
- Tabs renamed: Launch → Launcher, Keymap → Keysets.
- Invasions tab removed.

#### Settings tab redesign
- Section blocks sit on soft elevated surfaces with drop shadows and
  visible borders, matching the new design language.
- General settings collapse into an "Advanced" section (collapsible
  group with an animated rotating chevron).
- TTR + CC game-path settings merged into a single Games section with
  per-row "TTR" / "CC" leading pill chips.
- New `ButtonRow` widget covers Clear (destructive) and other action
  buttons with consistent theme handling.
- Row hover/focus states refined; sublabel font and section-title
  typography aligned with the rest of the app.

#### Motion system
- New tri-state **Reduce Motion** preference in General settings:
  System default / On / Off. Honors the OS reduce-motion preference
  when set to "System default".
- Page transitions, chip animations, popup animations, and the new
  modern scrollbar all gate on this preference.

#### Modern auto-hide scrollbar
- Custom `AutoHideScrollBar` replaces native scrollbars in Launcher,
  Keysets, and Settings. Fades to fully transparent when idle, wakes
  on hover, wheel, or value change, then fades back out after an idle
  timer expires.
- Theme-aware (light/dark) and reduce-motion compliant (instant snap
  when motion is reduced).
- 12 px top/bottom + 6 px right margins so the thumb sits cleanly
  inside its scroll area.

#### Header polish
- Header strip taller (48 → 56 px) and now shows the app icon next to
  the brand text.
- Session status indicator shows Idle / Running with active toon count.
- Hint toggle is now a borderless icon button living in the header.
- New app icon (asset refresh) with a tinted variant for the
  `ttmt-beta` package.

#### Multitoon polish
- Empty multitoon cards now include an inline "Launch a game" link
  directing users to the Launcher tab.
- Profile-pills row labelled `PROFILE` for clarity.
- Idle bar drops the italic styling and uses the dedicated idle-text
  theme color.
- Disabled-state styling on the Enable buttons is now explicit (no
  more no-op opacity fallback).

#### Accessibility / theme
- Light-mode `slot_dim` color bumped from `#cbd5e1` to `#64748b` so it
  meets WCAG 3:1 contrast against its surrounding fill.
- Focus rings added to chip-rail chips and the hint toggle.
- Removed redundant `:disabled` opacity overrides that were producing
  no visible change.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.3.0-a-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.3.0-a-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `ToonTownMultiTool-v2.3.0-a-Windows-x86_64.zip` | Windows 10/11 |

Pre-release-channel Arch users: `paru -Syu` (or your preferred helper)
to pick up the new `ttmt-beta` package.

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead
of the default Fusion look) can install `adwaita-qt6` from the
official repos. This is an optional system-level package; it doesn't
ship with the app.

---

### Smoketest

This is an alpha. The full manual smoketest checklist is attached to
the GitHub Pre-release as `SMOKETEST.md`. If you're testing this
build, please run through it and report any regressions before
promotion to beta or stable.
