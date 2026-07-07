"""Qt-free toon-capture bridge for the emblem radial menu.

Maps launched host pids to (game, account_id) and records the in-world toon for
an account into a RecentToonsStore. Extracted from LaunchTab so the value-based
exit cleanup and capture logic are unit-testable without constructing the tab.
"""
from __future__ import annotations


class ToonCaptureBridge:
    def __init__(self, recent_toons_store):
        self._store = recent_toons_store
        self._pid_to_account: dict[int, tuple[str, str]] = {}

    def record_launch(self, pid: int, game: str, account_id: str) -> None:
        self._pid_to_account[pid] = (game, account_id)

    def clear_account(self, game: str, account_id: str) -> None:
        """Drop every pid mapped to (game, account_id). The game_exited signal
        carries no pid, so we clear by value; this also self-heals a leaked stale
        pid from a superseded launcher whose exit was swallowed by the guard."""
        target = (game, account_id)
        self._pid_to_account = {p: ga for p, ga in self._pid_to_account.items() if ga != target}

    def capture(self, pid: int, toon_name: str, dna: str = "", *,
                laff=None, max_laff=None, species=None, accent=None) -> None:
        ga = self._pid_to_account.get(pid)
        if not ga:
            return
        game, account_id = ga
        self._store.record(account_id, toon_name, game, dna,
                           laff=laff, max_laff=max_laff, species=species, accent=accent)


def toon_changed(last_seen: dict, wid_key: str, toon_name: str, dna: str,
                 laff=None) -> bool:
    """True if (toon_name, dna, laff) for wid_key differs from the last captured value."""
    return last_seen.get(wid_key) != (toon_name, dna, laff)
