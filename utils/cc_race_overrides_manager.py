"""Per-toon manual icon override persistence.

Stores `{toon_name: asset_stem}` in JSON under the app config dir.
Auto-detection still drives the default icon; this manager only stores
explicit user overrides.

File: `<config_dir>/cc_race_overrides.json`
Pattern matches utils/profile_manager.py / utils/settings_manager.py.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional


logger = logging.getLogger(__name__)


class CCRaceOverridesManager:
    """Loads on construct, persists on every mutation (atomic write)."""

    def __init__(self):
        from utils.build_flavor import config_dir as _config_dir
        config_dir = _config_dir()
        os.makedirs(config_dir, exist_ok=True)
        os.chmod(config_dir, 0o700)
        self._path = os.path.join(config_dir, "cc_race_overrides.json")
        self._overrides: dict[str, str] = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Only keep string -> string entries; ignore anything weird.
                self._overrides = {
                    k: v for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[CCRaceOverridesManager] failed to load: %s", e)

    def _save(self) -> None:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self._overrides, f, indent=2, sort_keys=True)
                f.flush()
            os.replace(tmp, self._path)
        except OSError as e:
            logger.warning("[CCRaceOverridesManager] failed to save: %s", e)
            # Best-effort cleanup of the tmp file; ignore secondary errors.
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, toon_name: str) -> Optional[str]:
        return self._overrides.get(toon_name)

    def set(self, toon_name: str, asset_stem: str) -> None:
        self._overrides[toon_name] = asset_stem
        self._save()

    def clear(self, toon_name: str) -> None:
        if toon_name in self._overrides:
            del self._overrides[toon_name]
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._overrides)
