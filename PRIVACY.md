# Privacy Policy

- **Project:** ToonTown MultiTool, by flossbud
- **Last updated:** 2026-05-27

## TL;DR

Nothing leaves your device except your own login traffic, and that goes directly to the official Toontown Rewritten or Corporate Clash servers. There is no telemetry, no analytics, no crash reporting. The developer never receives any of your data.

## About

- **Author:** flossbud
- **Privacy contact:** flossbud27@gmail.com
- **Project:** https://github.com/flossbud/ToonTown-MultiTool

## Data stored locally on your device

For each item below: what is stored, where, and *why*. All app config
files under `~/.config/toontown_multitool/` are written with restrictive
POSIX permissions (`0700` directory / `0600` files) on Linux and macOS.

### Credentials

- **`accounts.json`** in `~/.config/toontown_multitool/`. Usernames and labels only. **Why:** so the credentials editor knows which accounts you've configured and so you can launch a toon with one click instead of re-typing your password every session.
- **OS keyring entries.** Passwords are stored via the [`keyring`](https://pypi.org/project/keyring/) library in your operating system's native credential store: Secret Service / KWallet on Linux, Keychain on macOS, Credential Locker on Windows. **Why:** so passwords stay encrypted at rest under your authenticated user session.
- **In-memory password fallback.** Used only when the keyring is unavailable. Passwords are held in volatile process memory and cleared on app exit or after one hour, whichever comes first. Never written to disk.

### App preferences and gameplay state

- **`settings.json`** in `~/.config/toontown_multitool/`. App-level preferences (update-check toggle, chat-handling mode, theme, and similar). **Why:** so your preferences persist across sessions.
- **`keymaps.json`** in `~/.config/toontown_multitool/`. Your custom movement key sets. **Why:** so custom keymaps survive restarts.
- **`profiles.json`** in `~/.config/toontown_multitool/`. Five named session profiles, each storing per-toon flags: enabled, movement mode, keep-alive, rapid-fire. **Why:** so your selected play style for each toon persists across sessions.
- **`toon_customizations.json`** in `~/.config/toontown_multitool/`. Per-toon overrides keyed by `<game>::<toon_name>`. Currently used for Corporate Clash race / species overrides applied when the local API can't disambiguate. **Why:** so per-toon UI matches your intent across sessions.

### Cached game art

- **`rendition_cache/`** in `~/.config/toontown_multitool/`. PNG files cached from `rendition.toontownrewritten.com`, named `<dna>__<pose>__<size>.png`. 24-hour TTL; expired entries are refetched on access. **Why:** so portrait images don't refetch on every UI redraw.

### Diagnostic logs

- **`keyring-debug.log`** in `~/.config/toontown_multitool/`. Contains keyring backend names, session/desktop environment info, probe timing, and account UUIDs (truncated to 8 characters in most lines). Does **not** contain passwords or usernames. **Why:** to help diagnose credential-storage issues in builds without a console (PyInstaller `--noconsole`, AppImage), where stdout would otherwise be lost.
- **`faulthandler.log`** in `~/.cache/toontown-multitool/` (note: cache dir, not config dir). Crash tracebacks written when the app receives `SIGSEGV` / `SIGBUS` / `SIGABRT`. Contains Python stack frames and thread state, no user data. **Why:** Python 3.14 + PySide6 6.10 has a known GC-during-paint race; a persistent log helps reproduce and fix it.

### Volatile, never persisted

- **In-memory live toon state.** Toon name, style/DNA, head color, current and max laff, bank beans. Fetched from the local game's API, held only while the app is running, never written to disk. **Why:** to populate the multitoon UI (toon cards, slot ordering) for the windows you currently have open.

## Data transmitted to third parties

- **When you launch a toon.**
  - **Toontown Rewritten:** your username and password are sent to `https://www.toontownrewritten.com/api/login`.
  - **Corporate Clash:** the app talks to four endpoints under `https://corporateclash.net/api/launcher/v1/`:
    - `register`, first-time device registration that binds your account to this device
    - `login`, credential check that returns a launch token
    - `metadata`, fetches launcher build metadata so versions match
    - `revoke_self`, revokes the device registration when you sign out
  - The respective game operators' privacy policies cover that traffic.
- **When the app fetches toon portrait images.** Requests go to `https://rendition.toontownrewritten.com/render/<dna>/<pose>/<size>x<size>.png`. The transmitted values are your toon's DNA string (which encodes appearance, not identity) and the requested pose name. Responses are cached locally for 24 hours (see `rendition_cache/` above).
- **When the app fetches live toon stats.** Requests go to `localhost` ports 1547-1552 (the TTR Companion API) and never leave your machine.
- **OS keyring services.** Passwords saved via the keyring are managed by your operating system's credential service: Apple Keychain, Microsoft Credential Locker, GNOME Keyring (Secret Service), or KWallet. Their data-handling is governed by your OS vendor's privacy practices.
- **Update checks.** Covered in detail in the [Update checks](#update-checks) section below.
- **No telemetry, analytics, or crash reporting.** The app does not contact any server controlled by the developer.
- **No web tracking.** TTMultiTool is a desktop application. It does not use cookies, tracking pixels, fingerprinting, or any web-based tracking technology.
- **A note about younger players.** Toontown Rewritten and Corporate Clash are family-friendly games and may be played by children. TTMultiTool does not transmit any user data to the developer, including from minors. The local-storage and login-transmission behavior described above applies equally to all users.

## How we secure your data

- **Passwords** rely on your OS-native credential store. On supported platforms these stores keep credentials encrypted at rest and unlock them only inside your authenticated user session. The app does not implement its own encryption layer; we defer to the OS security model rather than rolling our own.
- **Account metadata, settings, keymaps, profiles, toon customizations, the diagnostic log, and the rendition cache** are written with restrictive POSIX permissions (`0700` directory / `0600` files) on Linux and macOS, so other users on the same machine cannot read them. On Windows the files inherit your user's default NTFS ACLs.
- **In-memory password fallback** (used only when the keyring is unavailable) is held in volatile process memory and cleared on app exit or after one hour, whichever comes first.

## Your control over your data

- **Retention.** Stored data is retained until you delete it. The in-memory password fallback expires automatically after one hour.
- **Full local control.** Because all data lives on your device, you have direct access to every file. You can read or edit the JSON files in `~/.config/toontown_multitool/` with any text editor, copy them between machines, or delete them at any time without contacting us.
- **Delete one account.** Remove it in the credentials editor (Launch tab). The keyring entry is deleted along with the metadata.
- **Delete all accounts at once.** Use "Clear All" in the credentials editor.
- **Delete everything the app stores.** Delete `~/.config/toontown_multitool/`.
- **Delete crash diagnostics.** Delete `~/.cache/toontown-multitool/`. Safe to remove at any time; the app recreates it on next launch.
- **Uninstalling does not remove your config or cache directory.** That cleanup is your choice.

## Update checks

When "Check for updates at startup" is enabled in Settings (or when you
click "Check now"), the app makes one HTTPS request to
`api.github.com/repos/flossbud/ToonTown-MultiTool/releases` to read
the public releases list. No user data, machine ID, or telemetry is
sent. The only identifying value is a `User-Agent` header in the form
`ToonTownMultiTool/<version>`.

You can disable update checks at any time in Settings, Updates.

## Future features

If we add features that store more data (for example, the planned Profile Builder, which would persist toon names, photos, and stats locally), we will update this policy and call out the change in the release notes / changelog. We will not silently expand what the app stores or transmits.

## Changes to this policy

This policy is versioned via the project's git history. The "Last updated" date at the top changes when the policy changes. Material changes are also called out in the release notes for the version that introduces them.

## Contact

- **Privacy questions:** flossbud27@gmail.com
- **General bugs / feature requests:** [GitHub Issues](https://github.com/flossbud/ToonTown-MultiTool/issues)
