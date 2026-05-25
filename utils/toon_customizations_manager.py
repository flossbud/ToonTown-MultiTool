"""Per-toon customization persistence, namespaced by (game, toon_name).

Stores `{ "<game>::<toon_name>": <customization-dict> }` in JSON under
the app config dir.

File: `<config_dir>/toon_customizations.json`
Pattern mirrors utils/cc_race_overrides_manager.py / utils/settings_manager.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Final


logger = logging.getLogger(__name__)

_KEY_RE: Final = re.compile(r"^(cc|ttr)::.+")


def _key(game: str, toon_name: str) -> str:
    return f"{game}::{toon_name}"


class ToonCustomizationsManager:
    """Loads on construct, persists on every mutation (atomic write)."""

    def __init__(self) -> None:
        from utils.build_flavor import config_dir as _config_dir
        config_dir = _config_dir()
        os.makedirs(config_dir, exist_ok=True)
        os.chmod(config_dir, 0o700)
        self._path = os.path.join(config_dir, "toon_customizations.json")
        self._legacy_path = os.path.join(config_dir, "cc_race_overrides.json")
        self._entries: dict[str, dict] = {}
        self._migrate_legacy()
        self._load()

    # -- Persistence -----------------------------------------------------------

    def _migrate_legacy(self) -> None:
        """One-time migration from cc_race_overrides.json. Idempotent: if
        the new file already exists, do nothing (the user has already been
        migrated or is on a fresh install).
        """
        if os.path.exists(self._path):
            return
        if not os.path.exists(self._legacy_path):
            return
        try:
            with open(self._legacy_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[ToonCustomizationsManager] legacy read failed: %s", e)
            return
        if not isinstance(data, dict):
            return
        migrated: dict[str, dict] = {}
        for name, stem in data.items():
            if isinstance(name, str) and isinstance(stem, str):
                migrated[_key("cc", name)] = {"icon_stem": stem}
        if not migrated:
            return
        # Write the new file via the same atomic dance the _save uses.
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(migrated, f, indent=2, sort_keys=True)
                f.flush()
            os.replace(tmp, self._path)
        except OSError as e:
            logger.warning("[ToonCustomizationsManager] migrate write failed: %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        # Rename the legacy file so we never migrate twice.
        try:
            os.replace(self._legacy_path, self._legacy_path + ".bak")
        except OSError as e:
            logger.warning("[ToonCustomizationsManager] legacy rename failed: %s", e)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[ToonCustomizationsManager] load failed: %s", e)
            return
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if not isinstance(k, str) or not _KEY_RE.match(k):
                continue
            if not isinstance(v, dict):
                continue
            self._entries[k] = v

    def _save(self) -> None:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self._entries, f, indent=2, sort_keys=True)
                f.flush()
            os.replace(tmp, self._path)
        except OSError as e:
            logger.warning("[ToonCustomizationsManager] save failed: %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass

    # -- Public API ------------------------------------------------------------

    def get(self, game: str, toon_name: str) -> dict:
        entry = self._entries.get(_key(game, toon_name))
        return dict(entry) if entry else {}

    def set(self, game: str, toon_name: str, customization: dict) -> None:
        k = _key(game, toon_name)
        if not customization:
            self._entries.pop(k, None)
        else:
            self._entries[k] = dict(customization)
        self._save()

    def clear(self, game: str, toon_name: str) -> None:
        if self._entries.pop(_key(game, toon_name), None) is not None:
            self._save()

    def all(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._entries.items()}
