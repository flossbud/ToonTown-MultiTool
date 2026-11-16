"""Headless toon session: the runtime behind the float strips and the window.

``ToonSession`` owns everything about the running toons that is not painting:
which game windows exist, each toon's toggles and counters, the broadcast
service, keep-alive, click sync and profiles. It imports no widget code.

State is keyed by **window id** (the id ``WindowManager`` hands out), never by
list position. Consumers read immutable ``ToonState`` snapshots and react to
the four signals; they never reach around this surface.

Signal contract:

* ``toons_changed`` - a toon appeared, vanished or changed slot. Re-read
  ``toons()``; every snapshot held from before may be stale.
* ``toon_changed(window_id)`` - some other field of that toon changed.
* ``running_changed(bool)`` - the broadcast service started or stopped.
* ``features_changed`` - ``keep_alive_available()`` or
  ``click_sync_available()`` changed.

Every signal is emitted on the GUI thread. A setter that changes something
emits ``toon_changed`` exactly once; a setter that changes nothing (same
value, unknown window id, feature unavailable) emits nothing.

Click sync is only offered where ``ToonState.click_sync_supported`` is true;
``set_click_sync(window_id, True)`` is ignored for any other toon.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

GAME_TTR = "ttr"
GAME_CC = "cc"


def keyset_id_for_index(index: int) -> str:
    """Stable id of the keyset at ``index``.

    Until keysets carry their own ``"id"`` the position is the id. Everything
    that turns a position into an id (or back) goes through this pair, so the
    switch is one edit.
    """
    return str(int(index))


def keyset_index_for_id(keyset_id: str, default: int = 0) -> int:
    """Position of the keyset with ``keyset_id``; ``default`` when unknown."""
    try:
        index = int(keyset_id)
    except (TypeError, ValueError):
        return default
    return index if index >= 0 else default


def toon_identity(game: str, name: str | None) -> str | None:
    """Persistence key ``"<game>::<toon name>"``, or None while unnamed."""
    if not name:
        return None
    return f"{game}::{name}"


@dataclass(frozen=True)
class ToonState:
    window_id: str            # WindowManager id, stable for the window's life
    slot: int                 # 0-based order; "toon 1" is the lowest slot with a live window
    game: str                 # "ttr" | "cc"
    name: str | None          # None until the game API reports it
    species: str | None
    dna: str | None           # TTR only
    accent: str               # resolved toon colour "#rrggbb" (customization, else default)
    enabled: bool             # broadcast enable for this toon
    keep_alive: bool
    click_sync: bool
    click_sync_supported: bool  # False where click sync cannot run (Corporate Clash today)
    keyset_id: str            # stable id of the active keyset
    counters_locked: bool
    beans: int | None
    bank: int | None
    tokens: int | None        # Cartoonival; None when the API has no value
    laff: int | None
    max_laff: int | None

    @property
    def identity(self) -> str | None:
        return toon_identity(self.game, self.name)


class ToonSession(QObject):
    toons_changed = Signal()          # a toon appeared, vanished or changed slot
    toon_changed = Signal(str)        # any other field of that window_id's ToonState changed
    running_changed = Signal(bool)    # broadcast service started / stopped
    features_changed = Signal()       # app-wide availability flags changed

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    # ── Reads ──────────────────────────────────────────────────────────────

    def toons(self) -> list[ToonState]:
        """Every live toon, ordered by slot."""
        raise NotImplementedError

    def toon(self, window_id: str) -> ToonState | None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def keep_alive_available(self) -> bool:
        """App-wide keep-alive flag AND ToS consent."""
        raise NotImplementedError

    def click_sync_available(self) -> bool:
        raise NotImplementedError

    # ── Per-toon setters ───────────────────────────────────────────────────

    def set_enabled(self, window_id: str, on: bool) -> None:
        raise NotImplementedError

    def set_keep_alive(self, window_id: str, on: bool) -> None:
        raise NotImplementedError

    def set_click_sync(self, window_id: str, on: bool) -> None:
        raise NotImplementedError

    def set_keyset(self, window_id: str, keyset_id: str) -> None:
        raise NotImplementedError

    def set_counters_locked(self, window_id: str, on: bool) -> None:
        raise NotImplementedError

    # ── Session actions ────────────────────────────────────────────────────

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the broadcast service ("Stop all toons")."""
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-detect windows and re-poll the game APIs, with a cooldown."""
        raise NotImplementedError

    def load_profile(self, index: int) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        raise NotImplementedError

    # ── Handles for wiring that already exists in the shell ────────────────

    @property
    def input_service(self):
        raise NotImplementedError

    @property
    def key_event_queue(self):
        raise NotImplementedError

    @property
    def customizations(self):
        raise NotImplementedError

    @property
    def click_sync_service(self):
        raise NotImplementedError

    @property
    def ghost_cursor_controller(self):
        raise NotImplementedError

    def set_toon_capture_sink(self, sink) -> None:
        """``sink`` receives each toon the game APIs report, for the launcher."""
        raise NotImplementedError
