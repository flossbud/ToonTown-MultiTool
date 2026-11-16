"""Per-toon choices the session remembers across runs.

Keyed by toon identity ``"<game>::<toon name>"``, the key
``toon_customizations.json`` uses. Kept in a file of its own because the
looks editor replaces a toon's whole customization entry on save, which
would drop anything stored alongside it.

Fields: ``keyset_id`` (str) and ``counters_locked`` (bool). Unknown fields
in the file are preserved.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading

FILE_NAME = "toon_session.json"


class ToonPrefs:
    def __init__(self, path: str | None = None):
        if path is None:
            from utils.build_flavor import config_dir
            directory = config_dir()
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, FILE_NAME)
        self._path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:  # noqa: BLE001
            print(f"[ToonPrefs] Failed to load {self._path}: {e}")
            return
        toons = data.get("toons") if isinstance(data, dict) else None
        if isinstance(toons, dict):
            self._entries = {
                str(k): dict(v) for k, v in toons.items() if isinstance(v, dict)}

    def _save_locked(self) -> None:
        payload = {"version": 1, "toons": self._entries}
        directory = os.path.dirname(self._path) or "."
        try:
            fd, tmp = tempfile.mkstemp(prefix=".toon_session-", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, sort_keys=True)
                os.replace(tmp, self._path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:  # noqa: BLE001
            print(f"[ToonPrefs] Failed to save {self._path}: {e}")

    def get(self, identity: str | None) -> dict:
        """The stored fields for ``identity`` (a copy); empty when unknown."""
        if not identity:
            return {}
        with self._lock:
            return dict(self._entries.get(identity, {}))

    def update(self, identity: str | None, **fields) -> None:
        """Merge ``fields`` into the entry for ``identity`` and persist."""
        if not identity or not fields:
            return
        with self._lock:
            entry = self._entries.setdefault(identity, {})
            if all(entry.get(k) == v for k, v in fields.items()):
                return
            entry.update(fields)
            self._save_locked()
