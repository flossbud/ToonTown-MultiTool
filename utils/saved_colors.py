"""Global, capped palette of user-saved colors, persisted via SettingsManager."""
from __future__ import annotations

_KEY = "saved_colors"
_CAP = 6

class SavedColorsStore:
    """Persistent saved-color palette.

    Pass a SettingsManager for persistence. Pass None to get an
    ephemeral in-memory palette (useful for contexts without settings,
    e.g. unit tests or transient UI).
    """

    def __init__(self, settings):
        self._s = settings
        # When settings is None, fall back to an in-memory dict so all
        # methods still work without modification.
        self._mem: dict | None = {} if settings is None else None

    def get(self) -> list[str]:
        if self._mem is not None:
            raw = self._mem.get(_KEY, []) or []
        else:
            raw = self._s.get(_KEY, []) or []
        return [c for c in raw if isinstance(c, str)][:_CAP]

    def save(self, hex_: str) -> None:
        cur = self.get()
        if hex_ in cur:
            return
        cur.append(hex_)
        if self._mem is not None:
            self._mem[_KEY] = cur[:_CAP]
        else:
            self._s.set(_KEY, cur[:_CAP])

    def clear(self, index: int) -> None:
        cur = self.get()
        if 0 <= index < len(cur):
            del cur[index]
            if self._mem is not None:
                self._mem[_KEY] = cur
            else:
                self._s.set(_KEY, cur)
