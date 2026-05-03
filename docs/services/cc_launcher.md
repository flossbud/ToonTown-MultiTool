# services/cc_launcher.py

## Purpose

Launches Corporate Clash game instances with credentials passed as CLI arguments, monitors the process lifecycle, and registers the instance in `GameRegistry`. Mirrors `TTRLauncher` but uses CLI args (`-g`, `-t`) instead of environment variables.

---

## Constants

```python
_CUSTOM_APPROVAL_KEY = "cc_engine_dir_approved_custom_dir"
_TRUSTED_CC_ENGINE_DIRS  # set of realpath'd default CC install locations
```

---

## Module Functions

### `_is_trusted_cc_engine_path(engine_path, settings_manager)` → bool

Same validation logic as TTR's equivalent. Checks against trusted directories or user-approved custom path.

### `_approved_custom_engine_dir(settings_manager)` → str | None

Returns user-approved custom engine directory from settings.

---

## Class: `CCLauncher` (QObject)

### Signals

Same as `TTRLauncher`: `game_launched(int)`, `game_exited(int)`, `launch_failed(str)`.

### `launch(gameserver, osst_token, engine_dir)`

Launches the CC engine in a background thread:

1. Validates engine path
2. `build_launcher_env({})` — clean environment (CC doesn't inject creds via env)
3. `subprocess.Popen([engine_dir, "-g", gameserver, "-t", osst_token], env=clean_env)`
4. Registers PID as `"cc"` in `GameRegistry`
5. Emits `game_launched(pid)`, waits for exit, emits `game_exited(returncode)`

**Why CLI args?** Corporate Clash uses `-g <gameserver>` and `-t <osst_token>` command-line arguments instead of environment variables. Different game, different protocol.

### `kill()` / `is_running()`

Same as `TTRLauncher`.

---

## Dependencies

Same as `TTRLauncher` — `launcher_env`, `game_registry`, `subprocess`, `threading`.
