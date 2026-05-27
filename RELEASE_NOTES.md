## ToonTown MultiTool v0.6.0-alpha.3

Rebrand release. The project has moved to a pre-1.0 alpha line (`v0.X.Y-alpha.Z`) to better reflect maturity, and this release consolidates roughly six months of work since the prior release (formerly `v2.3.0-a1`, now `v0.6.0-alpha.2`).

Past releases `v1.0` through `v2.3.0-a1` have been retagged to `v0.1.0-alpha.1` through `v0.6.0-alpha.2`. Each renamed GitHub Release carries a "Previously released as" callout at the top of its body. The in-app updater now reads a single release feed (the prior stable-vs-beta channel split is gone); every install sees the same "latest" tag. AUR users on `toontown-multitool` and `ttmt-beta` migrate automatically via `epoch=1` on the next `paru -Syu`.

---

### Improvements

**Corporate Clash, Linux**
- Launch coverage now includes Bottles (Flatpak and native), Lutris-managed Wine prefixes, Steam Proton compatdata, Faugus, and plain `~/.wine` / `~/.local/share/wineprefixes`. Each launcher is invoked through its native runtime.
- New multi-install picker prompts when more than one Corporate Clash install is detected, with a Settings Auto-detect button that glows when a pick is needed.
- New Wine input bridge delivers multi-toon keyboard input to non-focused CC windows on Linux. Adds `PyYAML` as a Linux-only dependency.
- CC launch console is hidden by default; toggle in Settings if you want to see Wine output.

**Corporate Clash login + accounts**
- Migrated to CC's new launcher API (`/api/launcher/v1/*`). TTMT now stores a per-account launcher token instead of a password, aligned with CC's policy that third-party launchers should not store passwords. Existing accounts re-register silently on next launch.
- Token revocation fires when an account is removed, so CC's authorized-launchers list stays clean. Per-channel keyring namespaces so stable and beta installs do not cross-contaminate.
- Invalid tokens turn the affected account red with a clear "click Edit to re-enter your password" message.

**Per-toon Corporate Clash control**
- CC slots now support per-toon keysets the same way TTR does. CC `preferences.json` is locked to a canonical keymap on first launch (with a backup written to `preferences.json.ttmt-backup`).
- New X11 input grabber routes opposite-of-canonical keys to background toons via the Wine bridge during active focus, with auto-repeat coalescing and modifier passthrough.

**Perform Action**
- New logical action for TTR with per-keyset key assignment. Fires a verified per-toon keydown/keyup pair through the existing input service. Editable in the Keymap tab on TTR set cards.

**Multitoon, UI**
- Compact-mode redesign for the Multitoon tab.
- New customization overlay replaces the modal dialog, with scale-fade entry/exit animations and a backdrop blur. Pose-adjust UI redesigned for compact viewports (vertical stack, 3-column tile grid).
- New Chat Handling mode in the Features section of Settings replaces the old per-toon chat toggles. Phantom keyup activation is now gated on the chat-handling mode.

**Launch + Keymap, UI**
- Launch tab redesign with collapsible TTR / CC sections and persistence.
- Keysets tab design alignment with the rest of the app.
- Login failure dialog with explicit retry path.

**Settings + Keep-Alive**
- Settings tab redesign.
- Per-toon Keep-Alive discovery affordance lands across both TTR and CC cards.
- Settings group renamed from "Keep-Alive" to "Features" to accommodate Chat Handling and future toggles.

**Held-key tracking**
- Unified HeldKeyRegistry data structure tracks hold-duration across input backends.
- F1-F12 keysyms now forward to background toons (prior gap).

**In-app updater**
- The stable-vs-beta channel split is gone. Every install (stable AUR, `ttmt-beta` AUR, AppImage, Flatpak, EXE, .deb) reads the same release feed and picks the highest tag by tuple compare and suffix ordering. The prerelease flag is informational only.

**Distribution**
- Project rebranded from v2.x to a pre-1.0 alpha line.
- Both AUR packages (`toontown-multitool` and `ttmt-beta`) migrate to `epoch=1` so existing v2.x users upgrade automatically.
- Python 3.9 CI compatibility: deferred annotations applied across modules that used PEP 604 union syntax at function-definition time.

### Bug Fixes

A non-exhaustive list of representative fixes. Full commit history covers ~145 fix commits across this release.

- CC launch no longer hangs on repeat launches (Wine input bridge drain + per-prefix proton-run handling).
- Concurrent CC launches in the same Proton prefix now work.
- CC starts find their assets when the install lives in unusual Wine prefix layouts.
- Tokens are masked in plain-text diagnostics so terminal-paste bug reports do not leak credentials.
- KWallet probes no longer hang the startup screen (bounded Jeepney timeouts with SecretService fallback).
- Customization overlay close + refresh buttons render correctly with QIcon; panel translucency no longer triggers QPainter spam.
- Multitoon badge geometry is guarded during cross-layout transitions.
- Win32 movement grabber fixed.
- Wine bridge plain-wine launch path fixed.
- venv re-exec paths fixed on Windows and on restart-from-crash.
- Bottles launch errors classified by distribution and surfaced via a raw-error modal.
- MultiToonTool init crash fixed.
- Faugus Launch CLI integration fixed.
- dev-setup script handles Arch Python 3.14 path.

---

## Downloads

| Platform | Asset |
|---|---|
| Windows installer | `ToonTownMultiTool-Setup-v0.6.0-alpha.3-Windows-x86_64.exe` |
| Windows portable | `ToonTownMultiTool-v0.6.0-alpha.3-Windows-x86_64.zip` |
| Linux AppImage | `TTMultiTool-v0.6.0-alpha.3-Linux-x86_64.AppImage` |
| Linux Flatpak | `TTMultiTool-v0.6.0-alpha.3-Linux-x86_64.flatpak` |
| Linux .deb | `TTMultiTool-v0.6.0-alpha.3-Linux-x86_64.deb` |

## Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
git checkout v0.6.0-alpha.3
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
