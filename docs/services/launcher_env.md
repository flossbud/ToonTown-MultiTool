# services/launcher_env.py

## Purpose

Builds a filtered, safe environment dict for game process launches. Uses an **allowlist** approach — only known-safe environment variables are passed to child game processes. This prevents developer secrets (AWS credentials, GitHub tokens, API keys set in the shell environment) from leaking into game subprocesses.

---

## `build_launcher_env(extra)` → dict

Constructs the child environment by:
1. Starting from `os.environ` (the current process environment)
2. Keeping only variables that match the allowlist (exact names or prefixes)
3. Merging in `extra` dict (game-specific variables like `TTR_GAMESERVER`)

Returns the filtered dict, suitable for passing to `subprocess.Popen(env=...)`.

---

## Allowlist Categories

### Common (all platforms)

Exact vars: `HOME`, `PATH`, `USER`, `USERNAME`, `LOGNAME`, `LANG`, `LANGUAGE`, `SHELL`, `TERM`, `TMPDIR`, `TEMP`, `TMP`

Prefixes: `LC_*`

### POSIX (Linux/macOS)

Exact vars: X11/Wayland display (`DISPLAY`, `WAYLAND_DISPLAY`, `XAUTHORITY`), D-Bus (`DBUS_SESSION_BUS_ADDRESS`), XDG base dirs (`XDG_RUNTIME_DIR`, `XDG_DATA_DIRS`, etc.), session type (`XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`), audio (`PULSE_SERVER`), GPU (`LIBGL_ALWAYS_SOFTWARE`)

Prefixes: `XDG_*`, `QT_*`, `GTK_*`, `SDL_*`, `ALSA_*`, `PULSE_*`, `MESA_*`, `DXVK_*`, `VK_*`

### Windows

Exact vars: `SystemRoot`, `SystemDrive`, `WINDIR`, `ComSpec`, `PROGRAMFILES`, `PROGRAMDATA`, `APPDATA`, `LOCALAPPDATA`

Prefixes: `PROGRAMFILES*`, `COMMONPROGRAMFILES*`

---

## Design Rationale

An allowlist is safer than a blocklist because:
- New secret environment variables (e.g., a newly set `ANTHROPIC_API_KEY`) are blocked by default
- Blocklists require explicit enumeration of every possible secret name — impossible to keep complete
- Game processes don't need most dev environment variables to function

The `extra` dict overrides or adds to the filtered environment — used by `TTRLauncher` to inject `TTR_GAMESERVER` and `TTR_PLAYCOOKIE`.

---

## Dependencies

- `os`, `sys` only — no third-party dependencies
