## ToonTown MultiTool v2.3.0-a1

Second alpha of the v2.3.0 cycle. This iteration ships the Linux Corporate Clash story end-to-end (launching via Steam Proton, Bottles, Lutris, or system Wine, plus a new Wine-side input bridge so multi-toon keyboard input reaches non-focused CC windows), a per-game keyset system, an in-app update flow, and an interstitial Keep-Alive consent page in the Windows installer.

Smoke-test this build before promotion to beta or stable. See `SMOKETEST.md` attached to this Pre-release.

---

### Bug Fixes

- **Corporate Clash launch no longer hangs on repeat launches.** A leftover `TTMTWineInputBridge.exe` from a prior CC session counted as a Wine client and kept `wineserver` alive, so the next launch's Proton `waitforexitandrun` blocked forever on the prefix lock. The launcher now drains the bridge before spawning and again after CC exits.
- **Concurrent CC launches in the same Proton prefix work.** Subsequent launches use `proton run` instead of `waitforexitandrun`, so a second toon launches against the live wineserver instead of blocking until the first one quits.
- **CC starts find their assets.** The launcher sets cwd to the game install dir, fixing a Panda3D `OSError: Failed to read file: '/phase_3/audio/music.json'` crash that hit users whose CC install lived inside an unusual Wine prefix layout.
- **Tokens never appear in plain text in logs.** The CC login flow now masks `TT_PLAYCOOKIE` and `LAUNCHER_USER` in `print()` diagnostics; users pasting terminal output into bug reports no longer leak credentials.
- **KWallet probes no longer hang the startup screen.** The credentials manager now uses Jeepney with bounded timeouts for KWallet, falling back to SecretService if KWallet is unresponsive, instead of waiting indefinitely on a stalled DBus call.
- **`PasswordDeleteError` no longer disables the keyring.** Clearing a slot that holds no stored password is now a no-op instead of marking the whole backend unavailable.
- **Windows Keep-Alive consent dialog renders correctly.** The Inno Setup wizard now forward-declares its handler procedures so the script compiles, the consent heading is sized at 14pt, and Decline/Accept buttons replace the Next button only on the consent page.
- **AppImage launches under bundled Python 3.9.** PEP 604 union annotations (`X | None`) in two modules now use `from __future__ import annotations` so they evaluate lazily and do not raise `TypeError` at import time on the bundled interpreter.
- **CI Linux builds no longer error out on `git rev-list`.** Containerized AppImage and Flatpak jobs re-add the workspace as `safe.directory` before invoking git, avoiding CVE-2022-24765's dubious-ownership refusal.
- **Misleading Windows keyring banner removed.** The "not as Administrator" hint that suggested admin elevation would help no longer appears.

---

### Improvements

#### Linux: Wine input bridge for non-focused CC windows

- New C# helper (`TTMTWineInputBridge.exe`) is compiled into the active Wine prefix on first need and posts Win32 keyboard messages directly to CC HWNDs. Background CC windows now receive keystrokes that XSendEvent could not deliver to Proton/Wine clients.
- TCP-loopback protocol, deterministic per-prefix port (SHA1-derived), best-effort fallback to the Xlib backend when the bridge cannot be prepared.
- Active-window aware: when the focused CC window is the same one being addressed, the helper uses the existing focus rather than re-ordering; off-foreground windows get a temporary z-order shuffle.
- Numpad keysym mapping, modifier wrapping, X11/Win32 sort-order cross-check to guard against multi-monitor edge cases.
- Per-prefix backoff (`_BAD_PREFIXES` cooldown) so a transiently broken Wine Mono install does not permanently disable the bridge for a session.
- Bridge is packaged inside the Flatpak so `wine-mono` users can build the helper at runtime.

#### Linux: Corporate Clash launching

- Detects CC installs under Steam Proton, Bottles, Lutris, native Wine, and a user-approved custom path. Each is classified by structural markers (compatdata layout, bottle.yml, etc.) and only auto-trusted when those markers are present.
- Proton runtime selection cascade: explicit user override, then Steam's `CompatToolMapping` per-appid, then the install's `config_info`, then the newest installed Proton.
- Compat picker dialog uses the Proton nickname with a compact suffix in the Settings row so it is identifiable at a glance.
- Wraps the Proton launch in the Steam Linux Runtime entry-point and switches verb to `run` for re-launches against the same prefix.
- CC window discovery on Linux now identifies Proton-launched windows reliably for the multitoon flow.
- New launcher protocol: credentials are passed to CC.exe via environment variables (`TT_PLAYCOOKIE`, `TT_GAMESERVER`, `LAUNCHER_USER`, `REALM`, `SENTRY_ENVIRONMENT`) to match the 2026 official launcher.

#### Per-game keysets

- New v2 keymap schema with per-game sets (separate TTR and CC keysets in the same profile). Existing v1 keymaps migrate on load.
- Keysets tab gets a segmented TTR/CC control, per-game card render, within-set conflict highlighting, and a "Detect CC Settings" button parallel to the existing TTR detector.
- CC preferences (`preferences.json`) auto-detection populates the CC keyset on first run.
- Multitoon set selector is game-aware; a conflict marker appears when the active set has duplicate bindings within a game.
- Logical-action input pipeline replaces the legacy movement-mode strings; foreground-game cache resolves bindings against whichever game owns the active window.

#### In-app updates

- Settings tab gets an Updates section with channel selection (stable/beta) and a manual "Check now" affordance.
- Non-modal update banner appears in the main window when a newer release is available; clicking opens a confirmation dialog.
- Per-install-method runner: AppImage in-place replacement, Flatpak `flatpak update`, `.deb` via `dpkg -i`, AUR via `paru -Syu`, ZIP/installer direct download for Windows.
- Terminal launcher picks an appropriate emulator (xfce4-terminal, gnome-terminal, konsole, etc.) and shlex-quotes the command, so the update runner is auditable in-flight.
- Build-info loader (`utils/_build_info.py`) provides a stable build number and commit SHA for downgrade detection; the Windows installer persists the installed build number and blocks downgrades.
- First-launch defaults: update checks default to on; users can disable per-channel.

#### Windows installer: Keep-Alive consent page

- A new wizard page asks for explicit consent before enabling the Keep-Alive task, gated on the task actually being selected on the Tasks page. Page is skipped when Keep-Alive is unchecked.
- Decline auto-unchecks the task and advances; Accept advances with the task armed.
- Upgrade installs preserve the prior consent state so re-upgrading does not require re-accepting.

#### Build, CI, and packaging

- PyInstaller pinned and AppImage tool fetched by SHA from `AppImage/appimagetool` (continuous tag).
- Publish actions SHA-pinned; semver tag guard prevents accidental release runs on malformed tags.
- Weston readiness poll replaces a fixed sleep in the Wayland launch test.
- `.deb` version-encoding tolerates pre-release suffixes (`2.3.0-a1` becomes `2.3.0~a1` per Debian policy).
- Flatpak host_argv carve-out so `flatpak-spawn --host` arguments are not mistakenly masked as sensitive.

#### Misc polish and refactors

- `closeEvent` shutdown drains the input service, window manager, and the new wine input bridge so a clean app exit does not leave a wineserver pinned by orphan bridge processes.
- Logical-action send pipeline drops the legacy movement pipeline; held action keys release on focus loss, chat open, or explicit chat timeout.
- Numerous internal docstring and log-message clarifications surfaced by code review.

---

### Downloads

| File | Platform |
| ---- | -------- |
| `TTMultiTool-v2.3.0-a1-Linux-x86_64.AppImage` | Linux (any distro, no install) |
| `TTMultiTool-v2.3.0-a1-Linux-x86_64.flatpak` | Linux (Flatpak) |
| `TTMultiTool-v2.3.0-a1-Linux-x86_64.deb` | Debian / Ubuntu / Mint |
| `ToonTownMultiTool-v2.3.0-a1-Windows-x86_64.zip` | Windows 10/11 (portable) |
| `ToonTownMultiTool-Setup-v2.3.0-a1-Windows-x86_64.exe` | Windows 10/11 (installer) |

Pre-release-channel Arch users: `paru -Syu` (or your preferred helper) to pick up the new `ttmt-beta` package once the AUR push completes.

GNOME users wanting Adwaita-styled Qt widgets and decorations (instead of the default Fusion look) can install `adwaita-qt6` from the official repos. This is an optional system-level package; it does not ship with the app.

---

### Smoketest

This is an alpha. The full manual smoketest checklist is attached to the GitHub Pre-release as `SMOKETEST.md`. If you are testing this build, please run through it and report any regressions before promotion to beta or stable.
