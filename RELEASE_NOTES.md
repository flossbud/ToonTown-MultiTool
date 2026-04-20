# ToonTown MultiTool v2.0.1

Patch release with security hardening, reliability fixes, test coverage, and architecture cleanup.

---

## Security

- CC authentication token is now passed via environment variable instead of CLI argument (was visible in `ps`)
- Thread-safe locks added to shared global state in TTR API module
- In-memory password fallback now has a 1-hour TTL with user-facing warnings
- Network error messages sanitized - no more infrastructure details leaked to the UI
- HTTPS enforcement assertions on all login API URLs
- Settings file now written with `0600` permissions

## Reliability

- Chat state properly reset when game window loses focus
- Key events use blocking queue put with timeout instead of silent drop
- V1 credential migration archives old file instead of deleting before verification
- Keyring probe auto-triggers deferred v1 migration on completion
- Cumulative 5-second timeout on keyring backend recovery (prevents UI hang)
- Proper thread shutdown hooks for InputService and InvasionsTab
- Stale worker/launcher references nulled after signal disconnect
- xdotool timeout preserves previous active window instead of clearing
- Engine path validation checks file existence after symlink resolution
- Empty usernames rejected in account editor
- Concurrent 2FA prompts prevented per account slot

## Error Handling

- Bare `except` clauses replaced with specific exceptions across 5 files
- All caught exceptions now logged instead of silently swallowed
- Accounts with missing IDs skipped with warning instead of creating empty entries
- Index bounds check added for chat management loop

## Testing

- pytest infrastructure added (pytest.ini, conftest.py)
- 30 unit tests covering keymap manager, game registry, and profile manager
- Tests cover direction lookups, singleton behavior, profile persistence, thread safety

## Architecture

- Shared widgets (IOSToggle, IOSSegmentedControl, PulsingDot, SmoothProgressBar) extracted to `utils/shared_widgets.py`
- Icon generators (16 functions) extracted to `utils/icon_factory.py`
- Centralized settings key constants in `utils/settings_keys.py`
- Vestigial `keep_alive_tab.py` removed
- Keep-alive and rapid-fire state now persisted in profiles

## Polish

- Unused `Q_ARG` import removed
- `get_movement_modes()` result cached to avoid double evaluation
- Animation magic numbers extracted to named constants
- Animation signal disconnect-before-connect prevents accumulation
- Hardcoded pixel sizes replaced with DPI-aware minimum sizes

---

## Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.1-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.1-Linux-x86_64.AppImage` | Linux (X11 / Wayland via XWayland) |
