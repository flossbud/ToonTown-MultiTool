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
from dataclasses import dataclass, field
from pathlib import Path


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
    return CcSettings(
        keymap=dict(data.get("keymap") or {}),
        want_custom_controls=bool(data.get("want-Custom-Controls", False)),
        source_path=Path(path),
    )
