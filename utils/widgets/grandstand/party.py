"""The launch party: which accounts are staged, which is the main, per game.

Qt-free on purpose. The cap rule, the star's launch precedence and the
post-deletion pruning are the launcher's only genuinely stateful logic, so
they live where they can be tested without constructing a widget.

Selection order is preserved (it is the stage order); the star does not move
within `selected()`, only within `launch_order()`.
"""
from __future__ import annotations

from typing import Iterable, Optional

from utils.settings_keys import (
    LAUNCHER_ACTIVE_GAME, LAUNCHER_PARTY_CC, LAUNCHER_PARTY_TTR,
    LAUNCHER_STAR_CC, LAUNCHER_STAR_TTR,
)

# The hero stage has four slots (handoff §4.1b); the party may not exceed them.
# Accounts beyond the party launch individually from their card (spec Q1).
CAP = 4

GAMES = ("ttr", "cc")

_PARTY_KEY = {"ttr": LAUNCHER_PARTY_TTR, "cc": LAUNCHER_PARTY_CC}
_STAR_KEY = {"ttr": LAUNCHER_STAR_TTR, "cc": LAUNCHER_STAR_CC}


class LaunchParty:
    """Selection, star and active game, persisted through a settings manager.

    A `None` settings manager is supported (tests, demo mode): state is held in
    memory and simply not persisted.
    """

    def __init__(self, settings_manager=None) -> None:
        self._sm = settings_manager
        self._sel: dict[str, list[str]] = {g: self._load_sel(g) for g in GAMES}
        self._star: dict[str, Optional[str]] = {g: self._load_star(g) for g in GAMES}
        self._active = self._load_active()

    # ── load helpers (defensive: stored JSON is user-editable) ─────────────

    def _get(self, key, default=None):
        return self._sm.get(key, default) if self._sm is not None else default

    def _set(self, key, value) -> None:
        if self._sm is not None:
            self._sm.set(key, value)

    def _load_sel(self, game: str) -> list[str]:
        """Stored selections are user-editable JSON. Duplicates must be
        collapsed before the cap is applied: a repeated id would otherwise
        occupy two stage slots, be dispatched twice by `launch_order`, and
        survive a `toggle` that removed only one occurrence."""
        raw = self._get(_PARTY_KEY[game], [])
        if not isinstance(raw, list):
            return []
        ids: list[str] = []
        for x in raw:
            if isinstance(x, str) and x and x not in ids:
                ids.append(x)
        return ids[:CAP]

    def _load_star(self, game: str) -> Optional[str]:
        raw = self._get(_STAR_KEY[game])
        return raw if isinstance(raw, str) and raw else None

    def _load_active(self) -> str:
        raw = self._get(LAUNCHER_ACTIVE_GAME, "ttr")
        return raw if raw in GAMES else "ttr"

    # ── active game ───────────────────────────────────

    def active_game(self) -> str:
        return self._active

    def set_active_game(self, game: str) -> None:
        """Unknown values are ignored rather than stored, so a corrupt setting
        can never strand the launcher on a game that does not exist."""
        if game not in GAMES:
            return
        self._active = game
        self._set(LAUNCHER_ACTIVE_GAME, game)

    # ── selection ─────────────────────────────────────

    def selected(self, game: str) -> list[str]:
        return list(self._sel[game])

    def is_selected(self, game: str, account_id: str) -> bool:
        return account_id in self._sel[game]

    def toggle(self, game: str, account_id: str) -> bool:
        """Add or remove an account. Returns False — and changes nothing — when
        a fifth account is refused; the shelf turns that into a shake, not a
        dialog (spec §7)."""
        sel = self._sel[game]
        if account_id in sel:
            sel.remove(account_id)
        elif len(sel) >= CAP:
            return False
        else:
            sel.append(account_id)
        self._persist_sel(game)
        return True

    def clear(self, game: str) -> None:
        """Empties the party. The star is a separate, persistent identity and
        is deliberately untouched."""
        self._sel[game] = []
        self._persist_sel(game)

    # ── star ─────────────────────────────────────────

    def star(self, game: str) -> Optional[str]:
        return self._star[game]

    def set_star(self, game: str, account_id: Optional[str]) -> None:
        self._star[game] = account_id or None
        self._set(_STAR_KEY[game], self._star[game] or "")

    # ── derived ──────────────────────────────────────

    def launch_order(self, game: str) -> list[str]:
        """Dispatch order for Play: the starred account first when it is in the
        party, then selection order (spec Q3, §6)."""
        sel = self.selected(game)
        star = self._star[game]
        if star and star in sel:
            sel.remove(star)
            return [star] + sel
        return sel

    def prune(self, game: str, valid_ids: Iterable[str]) -> None:
        """Drop selections and a star that name accounts which no longer exist.
        Runs on load and after any account delete (spec §7)."""
        valid = set(valid_ids)
        self._sel[game] = [a for a in self._sel[game] if a in valid]
        self._persist_sel(game)
        if self._star[game] is not None and self._star[game] not in valid:
            self.set_star(game, None)

    def _persist_sel(self, game: str) -> None:
        self._set(_PARTY_KEY[game], list(self._sel[game]))
