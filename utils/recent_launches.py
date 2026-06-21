"""Recent-launch MRU + menu-model logic for the emblem right-click launch menu.

Qt-free and unit-testable. The store persists an ordered list of account IDs
(front = most recent). The pure functions decide what the right-click menu shows;
all display + eligibility data is resolved fresh at build time because it is
volatile (keyring lock state, running state, renamed labels, deleted accounts).
"""
from __future__ import annotations


class RecentLaunchesStore:
    """Ordered MRU of account IDs, persisted via a settings_manager.

    ``settings_manager`` must expose ``get(key, default)`` and ``set(key, value)``;
    pass ``None`` to degrade to a no-op (no persistence, always empty).
    """

    _KEY = "recent_launches"
    _CAP = 10

    def __init__(self, settings_manager):
        self._sm = settings_manager

    def ordered_ids(self) -> list[str]:
        if self._sm is None:
            return []
        raw = self._sm.get(self._KEY, [])
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, str)]

    def record(self, account_id: str) -> None:
        # Type-check first so a non-string never reaches the truthiness test.
        if not isinstance(account_id, str) or not account_id:
            return
        ids = [x for x in self.ordered_ids() if x != account_id]
        ids.insert(0, account_id)
        ids = ids[:self._CAP]
        if self._sm is not None:
            self._sm.set(self._KEY, ids)
