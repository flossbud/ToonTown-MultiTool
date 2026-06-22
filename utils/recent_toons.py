"""Per-account last-in-world toon record, persisted via a settings_manager.

Qt-free and unit-testable. Sibling of utils/recent_launches.py: where
RecentLaunchesStore keeps the MRU of account IDs, this keeps the most recent
toon observed in-world for each account (name + game + DNA) so the emblem
radial menu can render that account's customized portrait while offline.

``settings_manager`` must expose ``get(key, default)`` and ``set(key, value)``;
pass ``None`` to degrade to a no-op (never persists, always empty).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToonRecord:
    toon_name: str
    game: str
    dna: str


class RecentToonsStore:
    _KEY = "recent_toons"

    def __init__(self, settings_manager):
        self._sm = settings_manager

    def _read(self) -> dict:
        if self._sm is None:
            return {}
        raw = self._sm.get(self._KEY, {})
        return raw if isinstance(raw, dict) else {}

    def get(self, account_id: str) -> ToonRecord | None:
        entry = self._read().get(account_id)
        if not isinstance(entry, dict):
            return None
        name = entry.get("toon_name")
        game = entry.get("game")
        if not isinstance(name, str) or not name or game not in ("ttr", "cc"):
            return None
        dna = entry.get("dna")
        return ToonRecord(name, game, dna if isinstance(dna, str) else "")

    def record(self, account_id: str, toon_name: str, game: str, dna: str = "") -> None:
        if not isinstance(account_id, str) or not account_id:
            return
        if not isinstance(toon_name, str) or not toon_name:
            return
        if game not in ("ttr", "cc"):
            return
        data = self._read()
        new_entry = {
            "toon_name": toon_name,
            "game": game,
            "dna": dna if isinstance(dna, str) else "",
        }
        if data.get(account_id) == new_entry:
            return  # unchanged -> skip the settings write + on_change callback fanout
        data[account_id] = new_entry
        if self._sm is not None:
            self._sm.set(self._KEY, data)
