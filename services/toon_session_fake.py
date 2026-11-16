"""In-memory stand-in for ``ToonSession``.

Same public surface and the same signal behaviour, with no game windows,
services or files behind it. The strips and the window are developed and
render-tested against this; ``FakeToonSession.demo()`` gives the four toons
of the design handoff.

Beyond the shared surface it has a few driver methods for tests and harnesses
(``add_toon``, ``remove_toon``, ``update_toon``, ``set_features``,
``set_profile``) that play the part of the outside world: a game window
opening, the game API reporting new numbers, a setting being flipped.
"""

from __future__ import annotations

import queue
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from services.toon_session import (
    GAME_CC,
    GAME_TTR,
    ToonState,
    keyset_id_for_index,
)

# Fields a profile may carry in the fake, in the order the real one applies them.
_PROFILE_FIELDS = ("enabled", "keep_alive", "keyset_id")


class FakeToonSession(QObject):
    toons_changed = Signal()
    toon_changed = Signal(str)
    running_changed = Signal(bool)
    features_changed = Signal()

    def __init__(self, toons=(), *, running: bool = False,
                 keep_alive_available: bool = True,
                 click_sync_available: bool = True,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._toons: dict[str, ToonState] = {}
        for state in toons:
            if state.window_id in self._toons:
                raise ValueError(f"duplicate window id {state.window_id!r}")
            self._toons[state.window_id] = state
        self._running = bool(running)
        self._keep_alive_available = bool(keep_alive_available)
        self._click_sync_available = bool(click_sync_available)
        self._profiles: dict[int, dict[int, dict]] = {}
        self._key_event_queue: queue.Queue = queue.Queue()
        self._toon_capture_sink = None
        self._shut_down = False

        # Call records, for tests that only need to know an action was asked for.
        self.refresh_count = 0
        self.loaded_profiles: list[int] = []

    # ── Demo data ──────────────────────────────────────────────────────────

    @classmethod
    def demo(cls, window_ids=None, parent: QObject | None = None) -> "FakeToonSession":
        """Four toons like the handoff screenshots, broadcast running.

        ``window_ids`` replaces the placeholder ids, in slot order, so a
        harness can point the demo toons at real stand-in windows.
        """
        ids = list(window_ids) if window_ids is not None else [
            "demo-1", "demo-2", "demo-3", "demo-4"]
        if len(ids) != 4:
            raise ValueError("demo() needs exactly four window ids")
        toons = [
            ToonState(
                window_id=str(ids[0]), slot=0, game=GAME_TTR, name="Flossbud",
                species="rabbit", dna=None, accent="#4a8fe7",
                enabled=True, keep_alive=True, click_sync=True,
                click_sync_supported=True,
                keyset_id=keyset_id_for_index(0), counters_locked=True,
                beans=456, bank=12840, tokens=310, laff=137, max_laff=137),
            ToonState(
                window_id=str(ids[1]), slot=1, game=GAME_TTR, name="Hector",
                species="dog", dna=None, accent="#e74a4a",
                enabled=True, keep_alive=True, click_sync=False,
                click_sync_supported=True,
                keyset_id=keyset_id_for_index(1), counters_locked=False,
                beans=87, bank=9200, tokens=42, laff=98, max_laff=112),
            ToonState(
                window_id=str(ids[2]), slot=2, game=GAME_CC, name="Moe",
                species="cat", dna=None, accent="#e7894a",
                enabled=True, keep_alive=False, click_sync=False,
                click_sync_supported=False,
                keyset_id=keyset_id_for_index(1), counters_locked=False,
                beans=1204, bank=30000, tokens=None, laff=64, max_laff=120),
            ToonState(
                window_id=str(ids[3]), slot=3, game=GAME_TTR, name="Linux",
                species="duck", dna=None, accent="#56c856",
                enabled=False, keep_alive=False, click_sync=False,
                click_sync_supported=True,
                keyset_id=keyset_id_for_index(0), counters_locked=False,
                beans=250, bank=6979, tokens=0, laff=15, max_laff=15),
        ]
        return cls(toons, running=True, parent=parent)

    # ── Reads ──────────────────────────────────────────────────────────────

    def toons(self) -> list[ToonState]:
        return sorted(self._toons.values(), key=lambda t: t.slot)

    def toon(self, window_id: str) -> ToonState | None:
        return self._toons.get(window_id)

    def is_running(self) -> bool:
        return self._running

    def keep_alive_available(self) -> bool:
        return self._keep_alive_available

    def click_sync_available(self) -> bool:
        return self._click_sync_available

    # ── Per-toon setters ───────────────────────────────────────────────────

    def set_enabled(self, window_id: str, on: bool) -> None:
        self._set_field(window_id, "enabled", bool(on))

    def set_keep_alive(self, window_id: str, on: bool) -> None:
        # Turning it on needs the feature; turning it off is always allowed.
        if on and not self._keep_alive_available:
            return
        self._set_field(window_id, "keep_alive", bool(on))

    def set_click_sync(self, window_id: str, on: bool) -> None:
        if on and not self._click_sync_available:
            return
        state = self._toons.get(window_id)
        if on and state is not None and not state.click_sync_supported:
            return
        self._set_field(window_id, "click_sync", bool(on))

    def set_keyset(self, window_id: str, keyset_id: str) -> None:
        self._set_field(window_id, "keyset_id", str(keyset_id))

    def set_counters_locked(self, window_id: str, on: bool) -> None:
        self._set_field(window_id, "counters_locked", bool(on))

    # ── Session actions ────────────────────────────────────────────────────

    def start(self) -> None:
        self._set_running(True)

    def stop(self) -> None:
        self._set_running(False)

    def refresh(self) -> None:
        self.refresh_count += 1

    def load_profile(self, index: int) -> None:
        """Apply the profile registered with ``set_profile``, if any."""
        self.loaded_profiles.append(index)
        for slot, fields in self._profiles.get(index, {}).items():
            state = self._toon_at_slot(slot)
            if state is None:
                continue
            changes = {k: fields[k] for k in _PROFILE_FIELDS if k in fields}
            self._apply(state.window_id, changes)

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._set_running(False)

    # ── Handles ────────────────────────────────────────────────────────────

    @property
    def input_service(self):
        return None

    @property
    def key_event_queue(self):
        return self._key_event_queue

    @property
    def customizations(self):
        return None

    @property
    def click_sync_service(self):
        return None

    @property
    def ghost_cursor_controller(self):
        return None

    def set_toon_capture_sink(self, sink) -> None:
        self._toon_capture_sink = sink

    # ── Drivers: the outside world, for tests and harnesses ────────────────

    def add_toon(self, state: ToonState) -> None:
        """A game window appeared."""
        if state.window_id in self._toons:
            raise ValueError(f"window id {state.window_id!r} already present")
        self._toons[state.window_id] = state
        self.toons_changed.emit()

    def remove_toon(self, window_id: str) -> None:
        """A game window went away. Unknown ids are ignored."""
        if self._toons.pop(window_id, None) is not None:
            self.toons_changed.emit()

    def update_toon(self, window_id: str, **fields) -> None:
        """Something outside the setters changed a toon (API poll, re-slotting).

        A slot change emits ``toons_changed``; any other change emits
        ``toon_changed``. Both fire, slot first, when both kinds change.
        """
        self._apply(window_id, fields)

    def set_features(self, *, keep_alive_available: bool | None = None,
                     click_sync_available: bool | None = None) -> None:
        """An app-wide flag changed. Per-toon toggles are left as they are,
        as in the app: a toon keeps its keep-alive choice while the feature
        is switched off."""
        changed = False
        if (keep_alive_available is not None
                and bool(keep_alive_available) != self._keep_alive_available):
            self._keep_alive_available = bool(keep_alive_available)
            changed = True
        if (click_sync_available is not None
                and bool(click_sync_available) != self._click_sync_available):
            self._click_sync_available = bool(click_sync_available)
            changed = True
        if changed:
            self.features_changed.emit()

    def set_profile(self, index: int, by_slot: dict[int, dict]) -> None:
        """Register what ``load_profile(index)`` applies: ``{slot: {field: value}}``
        with fields from ``enabled``, ``keep_alive``, ``keyset_id``."""
        self._profiles[index] = {int(s): dict(f) for s, f in by_slot.items()}

    # ── Internals ──────────────────────────────────────────────────────────

    def _toon_at_slot(self, slot: int) -> ToonState | None:
        for state in self._toons.values():
            if state.slot == slot:
                return state
        return None

    def _set_field(self, window_id: str, field: str, value) -> None:
        self._apply(window_id, {field: value})

    def _apply(self, window_id: str, fields: dict) -> None:
        old = self._toons.get(window_id)
        if old is None or not fields:
            return
        new = replace(old, **fields)
        if new == old:
            return
        self._toons[window_id] = new
        slot_changed = new.slot != old.slot
        other_changed = replace(new, slot=old.slot) != old
        if slot_changed:
            self.toons_changed.emit()
        if other_changed:
            self.toon_changed.emit(window_id)

    def _set_running(self, running: bool) -> None:
        if running == self._running:
            return
        self._running = running
        self.running_changed.emit(running)
