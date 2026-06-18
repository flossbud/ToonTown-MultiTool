"""Global, capped palette of user-saved colors, persisted via SettingsManager."""
from __future__ import annotations

_KEY = "saved_colors"
_CAP = 6

class SavedColorsStore:
    def __init__(self, settings):
        self._s = settings

    def get(self) -> list[str]:
        raw = self._s.get(_KEY, []) or []
        return [c for c in raw if isinstance(c, str)][:_CAP]

    def save(self, hex_: str) -> None:
        cur = self.get()
        if hex_ in cur:
            return
        cur.append(hex_)
        self._s.set(_KEY, cur[:_CAP])

    def clear(self, index: int) -> None:
        cur = self.get()
        if 0 <= index < len(cur):
            del cur[index]
            self._s.set(_KEY, cur)
