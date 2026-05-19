"""CC preferences.json reader. Discovers and parses CC's user config so the
'Detect CC Settings' button can populate the CC Default keyset.

Locations probed, in order:
  - Linux: <prefix>/drive_c/users/*/AppData/Local/Corporate Clash/preferences.json
           (wineuser varies: 'steamuser' for Steam-Proton/Bottles, $USER for
           plain Wine, etc.)
  - Windows native: %LOCALAPPDATA%/Corporate Clash/preferences.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from utils import logical_actions


@dataclass
class CcSettings:
    keymap: dict
    want_custom_controls: bool
    source_path: Path | None = None


def locate_cc_preferences(install) -> Path | None:
    """Resolve preferences.json from a discovered CC install record.

    `install` is expected to expose at least `prefix_path` (str) and
    optionally `launcher` (str). For 'native' Windows installs we use
    %LOCALAPPDATA% instead.
    """
    if sys.platform == "win32" and getattr(install, "launcher", "") == "native":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return None
        p = Path(local) / "Corporate Clash" / "preferences.json"
        return p if p.exists() else None

    prefix = getattr(install, "prefix_path", None)
    if not prefix:
        return None
    users_dir = Path(prefix) / "drive_c" / "users"
    if not users_dir.exists():
        return None
    for user in users_dir.iterdir():
        if not user.is_dir():
            continue
        candidate = user / "AppData" / "Local" / "Corporate Clash" / "preferences.json"
        if candidate.exists():
            return candidate
    return None


def parse_cc_preferences(path: Path) -> CcSettings:
    data = json.loads(Path(path).read_text())
    raw_keymap = data.get("keymap")
    keymap = dict(raw_keymap) if isinstance(raw_keymap, dict) else {}
    return CcSettings(
        keymap=keymap,
        want_custom_controls=bool(data.get("want-Custom-Controls", False)),
        source_path=Path(path),
    )


# CC preferences.json `keymap` dict key -> our logical action name.
# Inferred from the in-game options labels until a populated dict is observed
# in the wild; unknown keys are logged at apply time so the table can grow.
_CC_ACTION_NAME_MAP = {
    "forward": "forward",
    "reverse": "reverse",
    "left":    "left",
    "right":   "right",
    "jump":    "jump",
    "sprint":  "sprint",
    "gags":    "gags",
    "tasks":   "tasks",
    "book":    "book",
    "stickerbook": "book",  # alias seen in some CC builds
    "map":     "map",
    "showmap": "map",
}

# CC's binding value strings -> our keysym strings.
_CC_VALUE_TO_KEYSYM = {
    "shift":    "Shift_L",
    "control":  "Control_L",
    "ctrl":     "Control_L",
    "alt":      "Alt_L",
    "space":    "space",
    "escape":   "Escape",
    "enter":    "Return",
    "tab":      "Tab",
    "backspace": "BackSpace",
    "delete":   "Delete",
    "arrow_up":    "Up",    "up":    "Up",
    "arrow_down":  "Down",  "down":  "Down",
    "arrow_left":  "Left",  "left":  "Left",
    "arrow_right": "Right", "right": "Right",
}


def apply_cc_controls_to_set(keymap_manager, set_index: int, settings: CcSettings) -> int:
    """Apply CC bindings onto the CC bucket's set at set_index.

    - If want_custom_controls is False OR keymap is empty: write baked
      defaults from LogicalActionRegistry for every CC action.
    - Else translate known action-name keys via _CC_ACTION_NAME_MAP, then
      translate values via _CC_VALUE_TO_KEYSYM. Unknown action-name keys
      are logged; the corresponding action keeps its baked default.

    Returns the count of CC actions seeded from defaults (the defaults
    pass). In the custom-controls path this equals len(actions_for("cc"));
    overlay writes on top of those are not separately counted, so the
    return value is a "did something happen" signal rather than a count
    of overlay applications.
    """
    use_defaults = (not settings.want_custom_controls) or (not settings.keymap)
    n = 0

    if use_defaults:
        for action in logical_actions.actions_for("cc"):
            k = logical_actions.default_key("cc", action)
            if k is not None:
                keymap_manager.update_set_key("cc", set_index, action, k)
                n += 1
        return n

    # Start from defaults so unspecified actions stay sensible.
    for action in logical_actions.actions_for("cc"):
        k = logical_actions.default_key("cc", action)
        if k is not None:
            keymap_manager.update_set_key("cc", set_index, action, k)
            n += 1

    unknown_keys = []
    for raw_name, raw_val in settings.keymap.items():
        action = _CC_ACTION_NAME_MAP.get(str(raw_name).lower())
        if action is None:
            unknown_keys.append(raw_name)
            continue
        if not logical_actions.supports("cc", action):
            unknown_keys.append(raw_name)
            continue
        translated = _CC_VALUE_TO_KEYSYM.get(str(raw_val).lower(), raw_val)
        keymap_manager.update_set_key("cc", set_index, action, translated)

    if unknown_keys:
        print(f"[cc_settings] unknown keymap keys (will not migrate): {unknown_keys}")

    return n


# ── Write side (silent CC prefs lock for per-toon keyset support) ──────────

from dataclasses import dataclass

from utils import cc_isolation


@dataclass
class WriteResult:
    ok: bool
    backup_path: Path | None = None
    error: str | None = None


@dataclass
class RestoreResult:
    ok: bool
    error: str | None = None


def write_cc_canonical_keymap(
    prefs_path: Path,
    canonical: cc_isolation.Canonical,
) -> WriteResult:
    """Lock CC's preferences.json to a single movement keyset.

    Sets want-Custom-Controls=true, replaces the four movement bindings
    in `keymap` with the canonical's values, preserves all other keys
    (other keymap entries AND other top-level prefs). The original file
    is backed up to <prefs>.ttmt-backup on first call only -- subsequent
    writes keep that original intact.

    Atomic: writes to .ttmt-tmp then renames. Idempotent in outcome: if
    the keymap already matches, the file is rewritten with the same
    content (no-op semantically).
    """
    prefs_path = Path(prefs_path)
    backup_path = prefs_path.with_suffix(".json.ttmt-backup")
    tmp_path = prefs_path.with_suffix(".json.ttmt-tmp")

    try:
        if prefs_path.exists():
            existing = json.loads(prefs_path.read_text())
        else:
            existing = {}

        if prefs_path.exists() and not backup_path.exists():
            backup_path.write_text(prefs_path.read_text())

        keymap = dict(existing.get("keymap") or {})
        for action in cc_isolation.MOVEMENT_ACTIONS:
            keymap[action] = cc_isolation.CANONICAL_KEYMAP[canonical][action]

        updated = dict(existing)
        updated["keymap"] = keymap
        updated["want-Custom-Controls"] = True

        tmp_path.write_text(json.dumps(updated, indent=4))
        os.replace(tmp_path, prefs_path)

        return WriteResult(ok=True, backup_path=backup_path if backup_path.exists() else None)
    except OSError as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return WriteResult(ok=False, error=str(e))


def restore_cc_prefs(prefs_path: Path) -> RestoreResult:
    """Copy <prefs>.ttmt-backup back over <prefs> and remove the backup.

    There is no UI for this in TTMT; the function exists so power users
    or recovery tooling can call it manually. After restore, the next
    TTMT startup will re-lock the prefs (the backup creation guards
    against double-overwrite, so re-locking is safe but the user will
    see WASD again). To opt out permanently, delete the install or
    block TTMT from reaching the prefs path.
    """
    prefs_path = Path(prefs_path)
    backup_path = prefs_path.with_suffix(".json.ttmt-backup")
    tmp_path = prefs_path.with_suffix(".json.ttmt-tmp")

    if not backup_path.exists():
        return RestoreResult(ok=False, error=f"No backup at {backup_path}")

    try:
        tmp_path.write_text(backup_path.read_text())
        os.replace(tmp_path, prefs_path)
        backup_path.unlink()
        return RestoreResult(ok=True)
    except OSError as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return RestoreResult(ok=False, error=str(e))


def write_canonical_to_all_installs(
    installs: list,
    canonical: cc_isolation.Canonical,
) -> list[WriteResult]:
    """Apply write_cc_canonical_keymap to every discovered CC install.

    Skips installs with no preferences.json path. Returns a list parallel
    to the resolved paths.
    """
    results = []
    for inst in installs:
        path = locate_cc_preferences(inst)
        if path is None:
            continue
        results.append(write_cc_canonical_keymap(path, canonical))
    return results


def restore_all_installs(installs: list) -> list[RestoreResult]:
    results = []
    for inst in installs:
        path = locate_cc_preferences(inst)
        if path is None:
            continue
        results.append(restore_cc_prefs(path))
    return results
