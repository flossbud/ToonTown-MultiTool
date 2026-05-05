# Privacy Policy

**Last updated:** 2026-05-05
**Project:** ToonTown MultiTool, by flossbud

## TL;DR

Nothing leaves your device except your own login traffic, and that goes directly to the official Toontown Rewritten or Corporate Clash servers. There is no telemetry, no analytics, no crash reporting. The developer never receives any of your data.

## Who we are

- **Author:** flossbud
- **Privacy contact:** flossbud27@gmail.com
- **Project:** https://github.com/flossbud/ToonTown-MultiTool

## Data stored locally on your device

For each item below: what is stored, where, and *why*.

- **Account credentials.** Usernames and labels are stored in `~/.config/toontown_multitool/accounts.json`. Passwords are stored in your operating system's native credential store via the [`keyring`](https://pypi.org/project/keyring/) library — Secret Service / KWallet on Linux, Keychain on macOS, Credential Locker on Windows. If the keyring is unavailable, passwords are held only in volatile memory for up to one hour and are never written to disk. **Why:** so you can launch a toon with one click instead of re-typing your password every session, and so the credentials editor can show which accounts you've configured.
- **Profile settings.** Per-toon flags (enabled, movement mode, keep-alive, rapid-fire) are stored in `~/.config/toontown_multitool/profiles.json`. **Why:** so your selected play style for each toon persists across sessions.
- **Diagnostic log.** `~/.config/toontown_multitool/keyring-debug.log`. Contains keyring backend names, session/desktop environment info, probe timing, and account UUIDs (truncated to 8 characters in most lines). Does not contain passwords or usernames. **Why:** to help diagnose credential-storage issues in builds without a console (PyInstaller `--noconsole`, AppImage), where stdout would otherwise be lost.
- **In-memory live toon state.** Toon name, style/DNA, head color, current and max laff, bank beans. Fetched from the local game's API, held only while the app is running, never persisted to disk. **Why:** to populate the multitoon UI (toon cards, slot ordering) for the windows you currently have open.

## Data transmitted to third parties

- **When you launch a toon.** Your username and password are sent to the official Toontown Rewritten or Corporate Clash login servers, depending on which game you selected. The respective game operators' privacy policies cover that traffic.
- **OS keyring services.** Passwords saved via the keyring are managed by your operating system's credential service — Apple Keychain, Microsoft Credential Locker, GNOME Keyring (Secret Service), or KWallet. Their data-handling is governed by your OS vendor's privacy practices.
- **When the app fetches live toon stats.** Requests go to `localhost` ports 1547–1552 (the TTR Companion API) and never leave your machine.
- **No telemetry, analytics, or crash reporting.** The app does not contact any server controlled by the developer.
- **No web tracking.** TTMultiTool is a desktop application. It does not use cookies, tracking pixels, fingerprinting, or any web-based tracking technology.
- **A note about younger players.** Toontown Rewritten and Corporate Clash are family-friendly games and may be played by children. TTMultiTool does not transmit any user data to the developer, including from minors. The local-storage and login-transmission behavior described above applies equally to all users.

## How we secure your data

- **Passwords** rely on your OS-native credential store. On supported platforms these stores keep credentials encrypted at rest and unlock them only inside your authenticated user session. The app does not implement its own encryption layer — we defer to the OS security model rather than rolling our own.
- **Account metadata, profiles, and the diagnostic log** are written with restrictive POSIX permissions (`0700` directory / `0600` files) on Linux and macOS, so other users on the same machine cannot read them. On Windows the files inherit your user's default NTFS ACLs.
- **In-memory password fallback** (used only when the keyring is unavailable) is held in volatile process memory and cleared on app exit or after one hour, whichever comes first.

## Your control over your data

- **Retention.** Stored data is retained until you delete it. The in-memory password fallback expires automatically after one hour.
- **Full local control.** Because all data lives on your device, you have direct access to every file. You can read or edit the JSON files in `~/.config/toontown_multitool/` with any text editor, copy them between machines, or delete them at any time without contacting us.
- **Delete one account.** Remove it in the credentials editor (Launch tab). The keyring entry is deleted along with the metadata.
- **Delete all accounts at once.** Use "Clear All" in the credentials editor.
- **Delete everything the app stores.** Delete `~/.config/toontown_multitool/`.
- **Uninstalling does not remove your config directory** — that cleanup is your choice.

## Future features

If we add features that store more data — for example, the planned Profile Builder, which would persist toon names, photos, and stats locally — we will update this policy and call out the change in the release notes / changelog. We will not silently expand what the app stores or transmits.

## Changes to this policy

This policy is versioned via the project's git history. The "Last updated" date at the top changes when the policy changes. Material changes are also called out in the release notes for the version that introduces them.

## Contact

- **Privacy questions:** flossbud27@gmail.com
- **General bugs / feature requests:** [GitHub Issues](https://github.com/flossbud/ToonTown-MultiTool/issues)
