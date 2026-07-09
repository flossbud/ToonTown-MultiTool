# Privacy Policy

- **Project:** ToonTown MultiTool, by flossbud
- **Last updated:** 2026-07-09

## TL;DR

Nothing about you is sent to the developer. There is no telemetry, no analytics, no crash reporting. Your login credentials go directly to the official Toontown Rewritten or Corporate Clash servers and nowhere else.

To drive a toon in a window that is not focused, the app watches your keyboard and mouse while you play. Those keystrokes stay on your machine. They are never stored and never transmitted.

The app also downloads things that are not about you: game patch files from the official game servers, toon portrait images, and the list of MultiTool releases when you check for updates.

## About

- **Author:** flossbud
- **Privacy contact:** flossbud27@gmail.com
- **Project:** https://github.com/flossbud/ToonTown-MultiTool

## Where your data is stored

The app keeps everything in one configuration directory:

| Platform | Location |
|---|---|
| Linux | `$XDG_CONFIG_HOME/toontown_multitool`, or `~/.config/toontown_multitool` when that variable is unset |
| macOS | `~/Library/Application Support/toontown_multitool` |
| Windows | `%USERPROFILE%\.config\toontown_multitool` |

Beta builds (the `ttmt-beta` package and the Windows beta installer) use a separate directory ending in `_beta`, so a beta install never reads or writes your stable install's accounts and settings.

A small number of diagnostic files live in a cache directory instead: `$XDG_CACHE_HOME/toontown-multitool` or `~/.cache/toontown-multitool`. These are listed under [Diagnostic logs](#diagnostic-logs).

On Linux and macOS the configuration directory is created with restrictive POSIX permissions (`0700` directory), and the files holding credentials and settings are written `0600`, so other users on the same machine cannot read them. On Windows the files inherit your user's default NTFS ACLs.

## Data stored locally on your device

For each item below: what is stored, where, and *why*.

### Credentials

- **`accounts.json`.** Usernames and labels only, plus a random local ID per account. No passwords. **Why:** so the credentials editor knows which accounts you've configured and so you can launch a toon with one click instead of re-typing your password every session.
- **OS keyring entries (Linux and Windows).** Passwords are stored via the [`keyring`](https://pypi.org/project/keyring/) library in your operating system's native credential store: Secret Service or KWallet on Linux, Credential Locker on Windows. **Why:** so passwords stay encrypted at rest under your authenticated user session.
- **Encrypted vault (macOS only).** Passwords and Corporate Clash launcher tokens are stored in `vault.enc` in the configuration directory, encrypted with AES-256-GCM. The encryption key is stored next to it in `vault.key`, readable only by your user account. **Why:** the macOS build is currently ad-hoc signed, which means its code identity changes with every release. Keychain items are bound to that identity, so they would prompt you for approval again after every reboot and every update. Encrypting the file ourselves keeps credential access to a single Touch ID check per launch. See [How we secure your data](#how-we-secure-your-data) for the limits of this approach. When you first run a macOS build that has this vault, any passwords already in your Keychain are moved into it and the old Keychain items are removed.
- **Corporate Clash launcher tokens.** Corporate Clash issues a launcher token in exchange for your password the first time you register an account. The app stores that token (in the OS keyring on Linux and Windows, in the vault on macOS) and uses it for subsequent launches. **Why:** so your Corporate Clash password does not need to be kept or re-sent after the first registration.
- **In-memory password fallback.** Used only when the keyring is unavailable. Passwords are held in volatile process memory and cleared on app exit or after one hour, whichever comes first. Never written to disk.
- **`credentials.enc.migrated`.** A leftover from an older version of the app that kept an encrypted password file before the keyring was adopted. If you upgraded from such a version, the old file was renamed rather than deleted, so it may still be on disk. It is safe to delete.

### App preferences and gameplay state

- **`settings.json`.** App-level preferences (update-check toggle, chat-handling mode, theme, and similar). It also holds:
  - **`recent_toons`.** For each account, up to eight toons the app has seen you play, and which one you picked as that account's primary toon. Each record holds the toon's name, game, DNA string (which encodes appearance), laff, max laff, species, and accent color. **Why:** so the Launcher can show each account's primary toon as a real portrait, and so the Float UI accounts ring can draw those portraits without a game running.
  - **`recent_launches`.** The accounts you launched most recently, by local ID. **Why:** so the Float UI radial menu can offer them again.
  - **`hotkey_bindings` and `hotkey_launch_slots`.** Your global hotkey chords, and which account each launch slot points to. **Why:** so your hotkeys survive restarts.
- **`keymaps.json`.** Your custom movement key sets. **Why:** so custom keymaps survive restarts.
- **`profiles.json`.** Five named session profiles, each storing per-toon flags: enabled, movement mode, keep-alive, rapid-fire. **Why:** so your selected play style for each toon persists across sessions.
- **`toon_customizations.json`.** Per-toon appearance overrides keyed by `<game>::<toon_name>`: the chosen portrait icon and pose, card accent and body colors, and portrait styling (color, gradient, pattern, zoom, offset, rotation, outline, shadow). It also holds Corporate Clash race and species overrides applied when the game's own data can't disambiguate them. **Why:** so the toon cards you've customized look the same every session. Only these small style values are stored. No image data is written into this file.

### Cached game art

- **`rendition_cache/`** inside the configuration directory. PNG files cached from `rendition.toontownrewritten.com`, named `<dna>__<pose>__<size>.png`. 24-hour lifetime; expired entries are refetched on access. **Why:** so portrait images don't refetch on every UI redraw.

### Diagnostic logs

- **`keyring-debug.log`** in the configuration directory. Keyring backend names, session and desktop environment info, probe timing, and account IDs truncated to 8 characters. Does **not** contain passwords or usernames. Rotates past 256 KiB. **Why:** to help diagnose credential-storage issues in packaged builds without a console, where output would otherwise be lost.
- **`faulthandler.log`** in the cache directory. Crash tracebacks written when the app receives `SIGSEGV`, `SIGBUS`, or `SIGABRT`. Contains Python stack frames and thread state, no user data. **Why:** a known interaction between Python 3.14 and PySide6 6.10 can crash during painting; a persistent log helps reproduce and fix it.
- **`inject_helper.log`** in the cache directory, macOS only. Diagnostic output from the helper process that delivers clicks to background game windows. **Why:** that helper runs outside the app, so its errors would otherwise be invisible.
- **`perf_trace.log`** in the cache directory. Written only when you set `TTMT_PERF_TRACE=1`. UI timing measurements, no user data.
- **Game output captures.** When the app launches a game it captures that game's own console output to a temporary file. These are deleted when the game exits normally and kept when it crashes, so the failure can be diagnosed. They contain whatever the game client printed. Your credentials are handed to the game through its environment, not its console, and the app masks the sensitive values when it echoes that environment to its own log.
- **Keystroke trace, off by default.** Setting `TTMT_INPUT_TRACE=1` before launching makes the app append a line per key event to `/tmp/ttmt-input-trace.log`. Those lines contain the literal keys the input pipeline handled, which includes anything you typed into the game's chat box, and on macOS can include keys typed in other applications while a game window is open. It exists to debug input problems that cannot be reproduced from code alone. It is not exposed in the interface, is never enabled by a normal install, and requires you to set the variable yourself from a terminal. Nothing it writes is transmitted anywhere. Delete the file to remove it.

### Other files

- **X11 authority copy (Flatpak only).** Under Flatpak, the app copies your X11 authority cookie into its cache so it can start the game outside the sandbox. Written `0600`.

### Volatile, never persisted

- **Live toon state beyond the portrait fields.** Bank beans, current zone, and the list of game windows you have open are held only while the app is running and never written to disk. **Why:** to populate the toon cards for the windows you currently have open. The subset that *is* persisted (name, DNA, laff, max laff, species, accent) is described under `recent_toons` above.

## Keyboard and mouse input

This is the most privacy-sensitive thing the app does, so it is worth stating precisely.

To move a toon in a window that does not have focus, the app has to know which key you pressed in the window that does. It therefore observes keyboard and mouse input at the operating-system level while you play:

- **Linux:** the X11 RECORD extension, plus passive key grabs (`XGrabKey`) for movement keys and for the global hotkeys you configure. A grabbed hotkey is delivered by the X server to this app alone, so registering a hotkey does not widen what the app can see.
- **Windows:** a low-level keyboard hook.
- **macOS:** a Quartz event tap. This is what the Input Monitoring permission authorizes. Single-key hotkeys with a modifier are registered with the system directly instead, and never pass through the tap.

Keys observed this way are re-sent to your background game windows through local operating-system calls. They are never sent over a network and never seen by the developer. They are not written to disk either, unless you deliberately turn on the diagnostic trace described under [Diagnostic logs](#diagnostic-logs).

**What is watched, and when.**

On **Linux and Windows** the hook exists only while a game window or the MultiTool itself is focused. Switch to your browser, and the hook is removed. It cannot observe what you type into another application, because it is not installed while that application is in front.

On **macOS** the event tap stays installed for as long as any game window is open, even while you are working in another application. Removing and reinstalling the tap on every focus change stalls typing across the whole system for a moment, which is the worse behavior. While you are outside the game, every keystroke passes through the tap untouched: nothing is recorded, nothing is stored, nothing is acted on, and the app's suppression list is emptied so it cannot swallow a key meant for another program. The tap is removed when the last game window closes. The one exception is the opt-in keystroke trace described above, which is why that trace is documented rather than left silent.

The app does not take screenshots and does not read the pixels of any other application's window.

## macOS permissions

The macOS build asks for two permissions, both under System Settings, Privacy & Security:

- **Input Monitoring**, so the app can observe the keys and clicks you make while playing, as described above.
- **Accessibility**, so the app can deliver those keys and clicks to your background game windows.

It does not request Screen Recording, Full Disk Access, or automation control of other apps.

Access to your saved accounts is gated once per launch by macOS local authentication: Touch ID where available, falling back to your Mac login password. Cancelling that prompt leaves the accounts locked, and the app does not fall back to unlocked access. If your Mac has no password, passcode, or biometrics configured at all, there is no local security boundary to honor and the vault opens without prompting.

The macOS build is ad-hoc signed and has not been notarized by Apple, which is why macOS asks you to approve it on first launch.

## Data transmitted to third parties

- **When you launch a toon.**
  - **Toontown Rewritten:** your username and password are sent to `https://www.toontownrewritten.com/api/login`. Nothing else about your machine is sent.
  - **Corporate Clash:** the app talks to four endpoints under `https://corporateclash.net/api/launcher/v1/`:
    - `register`, first-time device registration that exchanges your username and password for a launcher token. This request also sends **your computer's hostname**, as part of the display name Corporate Clash shows in your account's list of authorized launchers.
    - `login`, exchanges the launcher token for a launch token
    - `metadata`, fetches launcher build metadata so versions match
    - `revoke_self`, revokes the device registration when you delete the account
  - The respective game operators' privacy policies cover that traffic.
- **When the app updates your game files.** Before each launch the app checks whether your game installation is current, and downloads any files that are missing or out of date. For Toontown Rewritten this contacts `www.toontownrewritten.com`, `cdn.toontownrewritten.com`, and the download mirror those return. For Corporate Clash it contacts `corporateclash.net` and the download server it names. These requests carry no user data. If the network is unavailable, the check is skipped and the launch proceeds.
- **When the app fetches toon portrait images.** Requests go to `https://rendition.toontownrewritten.com/render/<dna>/<pose>/<size>x<size>.png`. The transmitted values are your toon's DNA string (which encodes appearance, not identity) and the requested pose name. Responses are cached locally (see `rendition_cache/` above).
- **When the app reads live toon stats.** For Toontown Rewritten this queries `localhost` ports 1547 to 1552 (the TTR Companion API) and never leaves your machine. For Corporate Clash the app reads the game's own console output from a file on your disk; no request is made at all. Under Wine, keystroke forwarding uses a helper that listens on a loopback port, also never leaving your machine.
- **OS keyring services.** Passwords saved via the keyring on Linux and Windows are managed by your operating system's credential service: GNOME Keyring (Secret Service), KWallet, or Microsoft Credential Locker. Their data-handling is governed by your OS vendor's practices.
- **Update checks and update downloads.** Covered in detail in the [Update checks](#update-checks) section below.
- **No telemetry, analytics, or crash reporting.** The app does not contact any server controlled by the developer. TLS certificate verification is never disabled on any request the app makes.
- **No web tracking.** ToonTown MultiTool is a desktop application. It does not use cookies, tracking pixels, fingerprinting, or any web-based tracking technology.
- **A note about younger players.** Toontown Rewritten and Corporate Clash are family-friendly games and may be played by children. ToonTown MultiTool does not transmit any user data to the developer, including from minors. The local-storage and login-transmission behavior described above applies equally to all users.

## How we secure your data

- **Passwords on Linux and Windows** rely on your OS-native credential store. These keep credentials encrypted at rest and unlock them only inside your authenticated user session. The app does not add its own encryption layer on these platforms; it defers to the OS security model.
- **Passwords on macOS** are encrypted by the app with AES-256-GCM, because the OS credential store is impractical for an unsigned build (see [Credentials](#credentials)). The encryption key is stored in a separate file in the same directory, readable only by your user account. Stated plainly: this protects your passwords from other user accounts on the machine, and from anyone reading a backup, a synced folder, or a stray copy of the vault file without the key beside it. It does not protect them from a program already running as you. The Touch ID gate controls access through the app, not access to the file. When the macOS build is signed with a Developer ID, the key will move into the macOS data-protection Keychain and this gap closes.
- **Account metadata, settings, keymaps, profiles, toon customizations, the credential vault, and the rendition cache** are written with restrictive POSIX permissions (`0700` directory, `0600` files) on Linux and macOS. On Windows the files inherit your user's default NTFS ACLs.
- **The cache directory is not permission-restricted.** `faulthandler.log`, `inject_helper.log`, and `perf_trace.log` are written with your system's default permissions, which on most Linux and macOS systems means other users on the same machine can read them. They contain crash traces and timing data, not credentials or keystrokes. The same applies to the temporary game output captures.
- **In-memory password fallback** (used only when the keyring is unavailable) is held in volatile process memory and cleared on app exit or after one hour, whichever comes first.

## Your control over your data

- **Retention.** Stored data is retained until you delete it. The in-memory password fallback expires automatically after one hour.
- **Full local control.** Because all data lives on your device, you have direct access to every file. You can read or edit the JSON files in the configuration directory with any text editor, copy them between machines, or delete them at any time without contacting us.
- **Delete one account.** Remove it in the credentials editor (Launcher tab). The stored password and any launcher token are deleted along with the metadata, and Corporate Clash is told to revoke the device registration.
- **Delete all accounts at once.** Use "Clear All" in the credentials editor.
- **Delete everything the app stores.** Delete the configuration directory for your platform, listed in [Where your data is stored](#where-your-data-is-stored).
- **Delete diagnostics.** Delete `~/.cache/toontown-multitool/`. Safe to remove at any time; the app recreates it on next launch. If you ever enabled the keystroke trace, delete `/tmp/ttmt-input-trace.log` as well.
- **Uninstalling does not remove your configuration or cache directory.** That cleanup is your choice. The Windows uninstaller offers to remove it for you.

## Update checks

When "Check for updates at startup" is enabled in Settings, or when you click "Check now", the app makes one HTTPS request to `api.github.com/repos/flossbud/ToonTown-MultiTool/releases` to read the public releases list. No user data, machine ID, or telemetry is sent. The only identifying value is a `User-Agent` header in the form `ToonTownMultiTool/<version>`. The result is cached for six hours.

If you choose to install an update, the app downloads that release's installer from GitHub's public release asset hosting. For the AppImage and the Arch packages the app opens your browser or your package manager instead of downloading anything itself.

You can disable update checks at any time in Settings, under General.

## Future features

If we add features that store more data, we will update this policy and call out the change in the release notes and changelog. We will not silently expand what the app stores or transmits.

## Changes to this policy

This policy is versioned via the project's git history. The "Last updated" date at the top changes when the policy changes. Material changes are also called out in the release notes for the version that introduces them.

## Contact

- **Privacy questions:** flossbud27@gmail.com
- **General bugs / feature requests:** [GitHub Issues](https://github.com/flossbud/ToonTown-MultiTool/issues)
