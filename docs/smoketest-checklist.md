## Launch
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

## Background features
- [ ] Keep-alive fires on game window when enabled
- [ ] Keep-alive does not fire when disabled
- [ ] Invasion tracker updates
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
