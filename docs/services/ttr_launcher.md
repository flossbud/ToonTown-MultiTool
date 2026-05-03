# services/ttr_launcher.py

## Purpose

Launches TTREngine game instances with session credentials injected via environment variables, monitors the process lifecycle, and registers the instance in `GameRegistry`. Mirrors `CCLauncher` in structure.

---

## Constants

```python
_CUSTOM_APPROVAL_KEY = "ttr_engine_dir_approved_custom_dir"
_TRUSTED_ENGINE_DIRS  # set of realpath'd default TTR install locations
```

`_TRUSTED_ENGINE_DIRS` includes common locations: Flatpak app directories, `~/.steam`, system game paths, and Windows `Program Files` equivalents.

---

## Module Functions

### `_approved_custom_engine_dir(settings_manager)` → str | None

Returns the user-approved custom engine directory from settings, if any. The user can approve a non-standard install path through a settings UI prompt.

### `_is_trusted_engine_path(engine_path, settings_manager)` → bool

Validates that the engine path's parent directory is either in `_TRUSTED_ENGINE_DIRS` or matches the user-approved custom directory. Uses `os.path.realpath()` to resolve symlinks before comparison — prevents symlink tricks that would bypass the check.

Returns `False` (and does not launch) if the path is outside trusted locations.

---

## Class: `TTRLauncher` (QObject)

### Signals

```python
game_launched: Signal(int)   # PID
game_exited: Signal(int)     # return code
launch_failed: Signal(str)   # error message
```

### `launch(gameserver, cookie, engine_dir)`

Launches `TTREngine` in a background thread:

1. Validates engine path via `_is_trusted_engine_path()`
2. Calls `build_launcher_env({"TTR_GAMESERVER": gameserver, "TTR_PLAYCOOKIE": cookie})` to build a clean, safe child environment with credentials injected
3. `subprocess.Popen(engine_dir, env=clean_env)` — non-blocking launch
4. Registers the PID with `GameRegistry.instance().register(pid, "ttr")`
5. Emits `game_launched(pid)`
6. Waits for process exit, then emits `game_exited(returncode)` and unregisters from `GameRegistry`

**Why environment variables?** TTR passes credentials to the engine via `TTR_GAMESERVER` and `TTR_PLAYCOOKIE` env vars, not CLI arguments. This is the protocol defined by TTR's launcher.

### `kill()`

Terminates the game process (`process.terminate()`) if running.

### `is_running()` → bool

Returns True if the process is alive (`process.poll() is None`).

---

## Dependencies

| Module | Used for |
|--------|----------|
| `services/ttr_login_service.py` | `LoginState` (indirect) |
| `services/launcher_env.py` | `build_launcher_env()` |
| `utils/game_registry.py` | PID registration |
| `subprocess`, `threading`, `os` | Process management |
