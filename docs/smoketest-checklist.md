## Launch

CI launch-tests only a bare X server (xvfb) and a headless Wayland compositor —
it cannot run a real logged-in desktop session. Run the Launch, Credentials,
and UI sections below on each desktop environment:

- [ ] KDE Plasma (KWallet keyring backend)
- [ ] GNOME (Secret Service keyring backend)
- [ ] Cinnamon (Secret Service keyring backend)

- [ ] TTR launches into game
- [ ] CC launches into game
- [ ] Two toons launch simultaneously without interfering

## Credentials
- [ ] Login with stored password works
- [ ] Login with no stored password prompts, saves, persists across restart
- [ ] Keyring backend logs as detected on startup

## UI
- [ ] All tabs render without error
- [ ] Theme switching takes effect immediately
- [ ] Credits footer links open in default browser
- [ ] Keymap edits persist across restart
- [ ] Settings tab persists across restart

## v2.2 chip-rail navigation
- [ ] App opens at default 560×748 with header + chip rail visible above the tab content
- [ ] All four chips (Multitoon, Launch, Keymap, Settings) navigate correctly; selected chip shows accent border + larger tinted icon
- [ ] Clicking the header logo / title navigates to the Credits page (pointer cursor + "About / Credits" tooltip on hover)
- [ ] Hints toggle on the right of the chip rail still flips state; on-state shows accent background
- [ ] Toggle "Show Debug Tab" in Settings — the `⋯` overflow menu appears on the chip rail; menu → "View Logs" navigates to the Logs tab; toggling off hides the `⋯`
- [ ] Resize window to 1280×852 (or larger) — full-UI 2×2 multitoon card grid renders without compression
- [ ] Theme toggle (system/light/dark) updates chip rail colors, brand-link hover, and selected chip styling

## Background features
- [ ] Keep-alive fires on game window when enabled
- [ ] Keep-alive does not fire when disabled
- [ ] Multitoon controls route per-game (TTR vs CC don't cross over)

## Exit
- [ ] App exits cleanly with no orphan processes

## v2.1.3-a regression checks
Targeted repros for the seven in-scope fixes from the v2.1.3 beta report.

- [ ] **Issue 1 (credits asset, AUR build):** Open Credits tab on the AUR `ttmt-beta` install. The `flossbud` portrait must render (not an empty/blank centerpiece).
- [ ] **Issue 2 (credits theme follow):** Set TTMT theme to `system`. While the credits tab is open, toggle the OS between light and dark. The credits page colors must change in real time.
- [ ] **Issue 4 (Windows 150% DPI scaling):** Verified accept-as-is. Maximize TTMT on a 150%-scale Windows machine. The current "compact maximized" behavior is acceptable. Confirm no regression vs. v2.1.3 (still readable, no crashes).
- [ ] **Issue 5 (launch button state desync):** Launch a toon from the launch tab. The button must read `Quit` and the status dot must be green simultaneously, and remain so until the toon exits — including after any UI rebuild trigger (adding/editing/deleting another account, changing max-accounts-per-game).
- [ ] **Issue 6 (TTR settings auto-detect at startup):** Fresh TTMT install with default TTR settings. On first launch, the default keyset (Set 1) in the keymap tab must reflect TTR's controls without pressing the manual "Detect" button. Restart TTMT — the detected keymap must persist.
- [ ] **Issue 7 (Ctrl jump keep-alive on Windows):** TTR with default jump key (Left Ctrl). Enable keep-alive on a background toon. Toon must jump periodically. *Note: only Right Ctrl is a Win32 extended key; if Left-Ctrl-jump is still broken on Windows after the v2.1.3-a fix, that's a follow-up — not a v2.1.3-a regression.*
- [ ] **Issue 8 (arrow-key forwarding on Windows):** TTR with default arrow-key movement. Focus the foreground toon and press an arrow key. The background toons must move in sync.

### Chat-aware key-block rule (cross-cutting design improvement)
- [ ] **Default arrows config — chat-off blocks letters:** Configure TTR with default arrow-key movement (no letter hotkeys). Open chat on a background toon and turn chat OFF. Type letters in the foreground toon. Chat must NOT reopen on the background toon.
- [ ] **Letter hotkey config — chat-off blocks Enter only:** Configure TTR with at least one letter hotkey (e.g. WASD movement). Turn chat OFF on a background toon. Letters typed in the foreground must continue to forward (this is the existing v2.1.3 behavior — regression guard).

## v2.2.x input-forwarding regression checks

Targeted repros for the issues fixed in `2026-05-07-input-forwarding-fixes.md`.

### Modifier wparam fix (Issue 1)
- [ ] **Keep-alive Left Ctrl jump on default TTR (Windows):** Fresh TTR install, default keys (Left Ctrl = jump). Open TTMT v2.2.x, verify Set 1 jump = `L Ctrl`, set keep-alive action = "Jump", enable keep-alive on a background toon. The toon must visibly jump on the keep-alive interval.
- [ ] **Foreground Left Ctrl jump forwards to background toons:** Focus a TTR window. Press Left Ctrl. All other enabled toons must jump.
- [ ] **Right Ctrl forwarding (regression of v2.2.0 release-note claim):** Bind a TTR action to Right Ctrl in-game (use `Detect Game Settings` to refresh TTMT). Press Right Ctrl in the foreground TTR. Background toons must respond.
- [ ] **Right Alt + Right Shift + Left Shift forwarding:** Same procedure, one modifier at a time.
- [ ] **No regression for arrow-only keypresses:** Plain Up/Down/Left/Right (no Ctrl held) still forward.

### TTR vocabulary fix (Issue 2)
- [ ] **Arrow-key movement under default TTR (Windows):** Fresh TTR install. Open TTMT — Set 1 must show "Up Arrow", "Down Arrow", "Left Arrow", "Right Arrow" (not the literal `arrow_up`/`arrow_down`/...). Press an arrow key in the foreground TTR. Background toons must move.
- [ ] **F-key shortcut (Book = F8 by default):** Press F8 in foreground TTR. Background toons' Sticker Book must open.
- [ ] **Home / End forwarding (Gags / Tasks):** Same procedure with Home and End.

### Cache fallback
- [ ] **Settings.json briefly unreadable:** With a working keymap detected once, rename TTR's `settings.json`, restart TTMT. Set 1 must show the previously detected keymap (not WASD defaults). Restore the file.

### Mod-key sanity (no regressions)
- [ ] **Letter hotkeys still forward (custom WASD config):** Configure TTR for WASD movement in-game, click `Detect Game Settings`. Press W/A/S/D in foreground TTR. Background toons must move.
- [ ] **Chat-aware key blocking still gates correctly:** Toggle chat off on a background toon under default arrow TTR config. Type letters in foreground; background chat must NOT reopen.
