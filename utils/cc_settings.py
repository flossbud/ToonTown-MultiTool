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

    Returns the count of actions whose binding was written.
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
