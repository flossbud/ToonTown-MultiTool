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

import queue
import re
import threading
import time
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from services.chat_handling import compute_effective_chat_enabled
from services.click_sync_wiring import click_sync_supports_game
from services.keep_alive import (
    KEEP_ALIVE_ACTION_LABELS,
    KEEP_ALIVE_CONSENT_KEY,
    KEEP_ALIVE_MASTER_KEY,
    dispatch_keep_alive_cycle,
    keep_alive_delay_seconds,
)
from utils import cc_api
from utils.settings_keys import CLICK_SYNC_ENABLED
from utils.ttr_api import (
    clear_stale_names,
    get_toon_names_by_slot,
    invalidate_port_to_wid_cache,
)

GAME_TTR = "ttr"
GAME_CC = "cc"

# The routing layer (InputService, click sync, ghost cursors) addresses toons
# by position in WindowManager's window list and handles this many.
MAX_TOONS = 4

# Colour a toon gets before it has one of its own.
GAME_ACCENTS = {GAME_TTR: "#4a8fe7", GAME_CC: "#f26d21"}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _hex_colour(value) -> str | None:
    """``"#rrggbb"`` in lower case for a 3- or 6-digit hex colour, else None."""
    if not isinstance(value, str) or not _HEX_RE.match(value):
        return None
    digits = value[1:].lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits}"


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




class _Keysets:
    """The keysets of a game as the session needs them, by stable id.

    Everything is asked of ``KeymapManager`` at call time and nothing is
    kept: a set's position changes when sets are deleted or moved, its id
    does not. Without a keymap manager there are no keysets and every toon
    sits on the empty id at position 0.
    """

    def __init__(self, keymap_manager):
        self._keymap_manager = keymap_manager

    def known(self, game: str, keyset_id: str) -> bool:
        manager = self._keymap_manager
        return manager is not None and manager.index_of(game, keyset_id) >= 0

    def usable(self, game: str, keyset_id: str) -> bool:
        """Known and not hidden."""
        manager = self._keymap_manager
        return (manager is not None
                and manager.index_of(game, keyset_id) >= 0
                and not manager.is_hidden(game, keyset_id))

    def index(self, game: str, keyset_id: str) -> int:
        """Position InputService routes by; 0 (the base set) when unknown."""
        manager = self._keymap_manager
        if manager is None:
            return 0
        return max(0, manager.index_of(game, keyset_id))

    def name(self, game: str, keyset_id: str) -> str:
        manager = self._keymap_manager
        entry = manager.get_set_by_id(game, keyset_id) if manager is not None else None
        return entry.get("name", "Default") if entry else "Default"

    def id_for_name(self, game: str, name: str) -> str | None:
        """Id of the first set called ``name``. Profiles store sets by name,
        and names are not unique."""
        manager = self._keymap_manager
        if manager is None:
            return None
        for entry in manager.get_sets(game):
            if entry.get("name") == name:
                return entry.get("id")
        return None

    def lowest_visible(self, game: str) -> str:
        manager = self._keymap_manager
        if manager is None:
            return ""
        keyset_id = manager.lowest_visible_id(game)
        if keyset_id is None:
            ids = manager.get_set_ids(game)
            keyset_id = ids[0] if ids else ""
        return keyset_id


class _Toon:
    """Mutable record behind one ``ToonState``. GUI thread only."""

    __slots__ = (
        "window_id", "slot", "game", "name", "named_as", "species", "dna", "color",
        "enabled", "chat", "keep_alive", "rapid_fire", "click_sync",
        "keyset_id", "keyset_chosen", "counters_locked", "counters_chosen",
        "beans", "bank", "tokens", "laff", "max_laff", "state",
    )

    def __init__(self, window_id: str, slot: int, game: str, keyset_id: str):
        self.window_id = window_id
        self.slot = slot
        self.game = game
        self.name = None
        self.named_as = None         # last name seen, kept through a dropout
        self.species = None
        self.dna = None
        self.color = None            # colour the game reports for the toon
        self.enabled = True
        self.chat = True             # raw per-toon chat flag (per_toon mode)
        self.keep_alive = False
        self.rapid_fire = False
        self.click_sync = False
        self.keyset_id = keyset_id
        self.keyset_chosen = False   # set by the user in this window's life
        self.counters_locked = False
        self.counters_chosen = False
        self.beans = None
        self.bank = None
        self.tokens = None
        self.laff = None
        self.max_laff = None
        self.state = None            # last published ToonState

    def clear_game_data(self) -> None:
        self.name = self.species = self.dna = self.color = None
        self.beans = self.bank = self.tokens = self.laff = self.max_laff = None


def _default_input_service(**kwargs):
    from services.input_service import InputService
    return InputService(**kwargs)


def _default_click_sync(session):
    from services.click_sync_wiring import build_click_sync
    return build_click_sync(session._window_manager, session._settings, session)


class ToonSession(QObject):
    toons_changed = Signal()          # a toon appeared, vanished or changed slot
    toon_changed = Signal(str)        # any other field of that window_id's ToonState changed
    running_changed = Signal(bool)    # broadcast started / stopped
    features_changed = Signal()       # app-wide availability flags changed
    # InhibitStatus of the sleep inhibitor each time keep-alive (re)acquires it.
    keep_alive_inhibit_status = Signal(object)

    # Worker threads and plain callbacks hand their results to the GUI thread
    # through these.
    _ttr_data_ready = Signal(object)
    _cc_data_ready = Signal(object)
    _setting_changed = Signal(str, object)
    _keymaps_changed = Signal()

    # A refresh requested within this many seconds of the last accepted one
    # is dropped, so a held or mashed refresh key cannot stack InputService
    # restarts. Chosen to exceed the delayed toon-data fetch below.
    REFRESH_COOLDOWN_S = 1.5
    FETCH_DELAY_MS = 1200
    POLL_INTERVAL_MS = 5000

    def __init__(self, window_manager, *, settings_manager=None,
                 keymap_manager=None, profile_manager=None, logger=None,
                 customizations=None, prefs=None, sleep_inhibitor=None,
                 input_service_factory=None, click_sync_builder=None,
                 activate: bool = True, parent: QObject | None = None):
        """``activate=False`` builds everything but starts no thread, timer or
        window detection; call ``activate()`` when ready.

        ``input_service_factory(**kwargs)`` and ``click_sync_builder(session)``
        replace the real services (a builder may return None for "no click
        sync here").
        """
        super().__init__(parent)
        self._window_manager = window_manager
        self._settings = settings_manager
        self._keymap_manager = keymap_manager
        self._profile_manager = profile_manager
        self._logger = logger
        self._keysets = _Keysets(keymap_manager)

        if customizations is None:
            from utils.toon_customizations_manager import ToonCustomizationsManager
            customizations = ToonCustomizationsManager()
        self._customizations = customizations
        if prefs is None:
            from services.toon_prefs import ToonPrefs
            prefs = ToonPrefs()
        self._prefs = prefs

        self._toons: dict[str, _Toon] = {}
        self._order: list[str] = []
        self._running = True         # broadcast is on from the start
        self._activated = False
        self._shut_down = False
        self._active_profile = -1
        self._last_refresh_monotonic = float("-inf")
        # keyset / counter-lock choices carried across a refresh, which drops
        # and re-detects every window.
        self._refresh_carry: dict[str, tuple[str, bool]] = {}

        # What InputService and the keep-alive thread read, by slot. Each is
        # replaced whole (never mutated), so a reader on another thread always
        # sees one consistent list.
        self._slot_enabled = [False] * MAX_TOONS
        self._slot_chat = [True] * MAX_TOONS
        self._slot_assignments = [0] * MAX_TOONS
        self._slot_modes = ["Default"] * MAX_TOONS
        self._slot_keep_alive = [False] * MAX_TOONS
        self._slot_rapid_fire = [False] * MAX_TOONS

        self._key_event_queue: queue.Queue = queue.Queue(maxsize=200)

        # Toon polling.
        self._refresh_gen = 0
        self._fetch_inflight: set = set()
        self._toon_capture_sink = None
        self._last_captured: dict[str, tuple] = {}
        self._render_seen: dict[str, tuple] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._fetch_toon_data)
        self._fetch_timer = QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.timeout.connect(self._fetch_toon_data)
        self._ttr_data_ready.connect(self._apply_ttr_data)
        self._cc_data_ready.connect(self._apply_cc_data)

        # Keep-alive engine.
        self._keep_alive_running = False
        self._keep_alive_thread = None
        self._ka_cycle_start = 0.0
        self._ka_cycle_event = threading.Event()
        if sleep_inhibitor is None:
            from services.sleep_inhibitor import SleepInhibitor
            sleep_inhibitor = SleepInhibitor()
        self._sleep_inhibitor = sleep_inhibitor
        self._inhibit_worker = None
        self._inhibit_gen = 0
        self._retired_workers: list = []

        self._input_service = (input_service_factory or _default_input_service)(
            window_manager=window_manager,
            get_enabled_toons=self._get_enabled_toons,
            get_movement_modes=self._get_movement_modes,
            get_event_queue_func=self._get_key_event_queue,
            get_chat_enabled=self._get_chat_enabled,
            settings_manager=settings_manager,
            get_keymap_assignments=self._get_keymap_assignments,
            keymap_manager=keymap_manager,
            get_chat_handling_mode=self._get_chat_handling_mode,
        )
        # Foreground-game cache default until a game window has had focus.
        self._input_service._last_known_foreground_game = GAME_TTR
        input_log = getattr(self._input_service, "input_log", None)
        if input_log is not None:
            input_log.connect(self._on_input_log)

        # Click sync and ghost cursors.
        self._click_sync = (click_sync_builder or _default_click_sync)(self)
        self._click_sync_states: dict[int, str] = {}
        self._click_sync_error: str | None = None
        service = self.click_sync_service
        if service is not None:
            service.slot_states_changed.connect(self._on_click_sync_states)
            service.service_error.connect(self._on_click_sync_error)
        ghosts = self.ghost_cursor_controller
        if ghosts is not None:
            # The focused window never shows a ghost.
            focus = getattr(window_manager, "active_window_changed", None)
            if focus is not None:
                focus.connect(ghosts.set_focused_window)
            if hasattr(window_manager, "get_active_window"):
                ghosts.set_focused_window(window_manager.get_active_window() or "")

        # WindowManager emits from its poll thread. These are bound methods
        # of a QObject living on the GUI thread, so Qt queues the call across.
        window_manager.window_ids_updated.connect(self._on_window_ids)
        geometry = getattr(window_manager, "window_geometry_updated", None)
        if geometry is not None:
            geometry.connect(self._on_window_geometry)

        # Settings and keymap listeners are plain callbacks that may fire on
        # any thread: re-emit, and let Qt deliver on the GUI thread.
        self._setting_changed.connect(self._on_setting_changed)
        self._keymaps_changed.connect(self._on_keymaps_changed)
        if settings_manager is not None:
            settings_manager.on_change(self._setting_changed.emit)
        if keymap_manager is not None:
            keymap_manager.on_change(self._keymaps_changed.emit)
        self._keep_alive_was_available = self.keep_alive_available()
        self._click_sync_was_available = self.click_sync_available()
        self._apply_click_sync_master()

        if hasattr(window_manager, "get_window_ids"):
            self._on_window_ids(window_manager.get_window_ids())
        if activate:
            self.activate()

    def activate(self) -> None:
        """Start the InputService thread, window detection and toon polling."""
        if self._activated or self._shut_down:
            return
        self._activated = True
        print("[ToonSession] core active")
        self._window_manager.enable_detection()
        self._input_service.start()
        self._log("[Service] Multitoon service started.", level="ok")
        self._poll_timer.start()
        self._schedule_fetch()

    # ── Reads ──────────────────────────────────────────────────────────────

    def toons(self) -> list[ToonState]:
        """Every live toon, ordered by slot."""
        return [self._toons[wid].state for wid in self._order]

    def toon(self, window_id: str) -> ToonState | None:
        toon = self._toons.get(window_id)
        return toon.state if toon is not None else None

    def is_running(self) -> bool:
        return self._running

    def keep_alive_available(self) -> bool:
        """App-wide keep-alive flag AND ToS consent."""
        settings = self._settings
        return bool(
            settings
            and settings.get(KEEP_ALIVE_MASTER_KEY, False)
            and settings.get(KEEP_ALIVE_CONSENT_KEY, False)
        )

    def click_sync_available(self) -> bool:
        return bool(
            self.click_sync_service is not None
            and self._settings is not None
            and self._settings.get(CLICK_SYNC_ENABLED, False)
        )

    @property
    def active_profile(self) -> int:
        """Index of the profile last loaded, -1 when none."""
        return self._active_profile

    # ── Per-toon setters ───────────────────────────────────────────────────

    def set_enabled(self, window_id: str, on: bool) -> None:
        toon = self._toons.get(window_id)
        on = bool(on)
        if toon is None or toon.enabled == on:
            return
        toon.enabled = on
        toon.chat = on               # the raw chat flag follows the toon
        self._log(f"[Input] {self._label(toon)}: input "
                  f"{'enabled' if on else 'disabled'}")
        self._publish()
        self._autosave_active_profile()

    def set_keep_alive(self, window_id: str, on: bool) -> None:
        toon = self._toons.get(window_id)
        on = bool(on)
        if toon is None or toon.keep_alive == on:
            return
        if on and not self.keep_alive_available():
            return
        toon.keep_alive = on
        if on:
            self._reset_ka_cycle()
        else:
            # Turning it off always clears rapid fire, so the next turn-on
            # starts from the normal interval.
            toon.rapid_fire = False
        self._publish()

    def set_click_sync(self, window_id: str, on: bool) -> None:
        toon = self._toons.get(window_id)
        on = bool(on)
        service = self.click_sync_service
        if toon is None or service is None or toon.click_sync == on:
            return
        if on and not (self.click_sync_available()
                       and click_sync_supports_game(toon.game)):
            return
        toon.click_sync = on
        self._publish()

    def set_keyset(self, window_id: str, keyset_id: str) -> None:
        toon = self._toons.get(window_id)
        keyset_id = str(keyset_id)
        if toon is None or toon.keyset_id == keyset_id:
            return
        if not self._keysets.known(toon.game, keyset_id):
            return
        toon.keyset_id = keyset_id
        toon.keyset_chosen = True
        self._prefs.update(toon_identity(toon.game, toon.name), keyset_id=keyset_id)
        self._publish()
        self._autosave_active_profile()

    def set_counters_locked(self, window_id: str, on: bool) -> None:
        toon = self._toons.get(window_id)
        on = bool(on)
        if toon is None or toon.counters_locked == on:
            return
        toon.counters_locked = on
        toon.counters_chosen = True
        self._prefs.update(toon_identity(toon.game, toon.name), counters_locked=on)
        self._publish()

    def toggle_keep_alive_all(self) -> None:
        """If any toon's keep-alive is on, turn those off; otherwise turn it
        on for every toon. Nothing happens while keep-alive is unavailable."""
        if not self.keep_alive_available():
            return
        on = [wid for wid in self._order if self._toons[wid].keep_alive]
        for wid in (on or list(self._order)):
            self.set_keep_alive(wid, not on)

    # ── Session actions ────────────────────────────────────────────────────

    def start(self) -> None:
        self._set_running(True)

    def stop(self) -> None:
        """Stop broadcasting ("Stop all toons").

        The InputService thread, window detection and toon polling keep
        running; every toon is reported as not enabled to InputService, the
        keep-alive loop stops and click sync pauses. Each toon keeps its own
        flags, so ``start()`` restores exactly what was there.
        """
        self._set_running(False)

    def toggle_running(self) -> None:
        self._set_running(not self._running)

    def refresh(self) -> None:
        """Re-detect windows and re-poll the game APIs, with a cooldown."""
        if self._refresh_is_coalesced(time.monotonic()):
            self._log("[Service] Refresh coalesced (within cooldown).")
            return
        self._log("[Service] Manual refresh triggered.")
        invalidate_port_to_wid_cache()
        clear_stale_names([])
        self._refresh_carry = {
            wid: (toon.keyset_id, toon.counters_locked)
            for wid, toon in self._toons.items()
            if toon.keyset_chosen or toon.counters_chosen
        }
        while not self._key_event_queue.empty():
            try:
                self._key_event_queue.get_nowait()
            except Exception:  # noqa: BLE001
                break
        # Dropping the window list empties the session; the poll loop
        # re-detects within a couple of seconds and the toons come back.
        self._input_service.stop()
        self._window_manager.clear_window_ids()
        self._input_service.start()
        self._schedule_fetch()

    def load_profile(self, index: int) -> None:
        """Apply profile ``index`` to the live toons, by slot."""
        manager = self._profile_manager
        if not manager:
            return
        self._autosave_active_profile()     # the one being switched away from
        profile = manager.get_profile(index)
        self._active_profile = index
        enabled = profile.enabled_toons
        modes = profile.movement_modes
        keep_alive = profile.keep_alive or []
        rapid_fire = profile.rapid_fire or []
        for wid in self._order:
            toon = self._toons[wid]
            slot = toon.slot
            state = bool(enabled[slot]) if slot < len(enabled) else False
            toon.enabled = state
            toon.chat = state
            mode = modes[slot] if slot < len(modes) else "Default"
            keyset_id = self._keysets.id_for_name(toon.game, mode)
            if keyset_id is not None and keyset_id != toon.keyset_id:
                toon.keyset_id = keyset_id
                toon.keyset_chosen = True
                self._prefs.update(toon_identity(toon.game, toon.name),
                                   keyset_id=keyset_id)
            # Flags are taken as stored even while keep-alive is unavailable:
            # the loop only runs once the feature is on.
            toon.keep_alive = bool(keep_alive[slot]) if slot < len(keep_alive) else False
            toon.rapid_fire = bool(rapid_fire[slot]) if slot < len(rapid_fire) else False
        self._publish()
        self._log(f"[Profile] Loaded '{manager.get_name(index)}'")

    def customization_changed(self, game: str | None = None,
                              name: str | None = None) -> None:
        """The looks store changed (for ``game``/``name``, or anything when
        omitted): re-resolve the accent of the toons it touches."""
        del game, name     # every snapshot is cheap to rebuild
        self._publish()

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._stop_keep_alive()
        self._poll_timer.stop()
        self._fetch_timer.stop()
        self._refresh_gen += 1          # drop any fetch still in flight
        self._input_service.shutdown()
        if self._click_sync is not None:
            self._click_sync.shutdown()

    # ── Handles for wiring that already exists in the shell ────────────────

    @property
    def input_service(self):
        return self._input_service

    @property
    def key_event_queue(self):
        return self._key_event_queue

    @property
    def customizations(self):
        return self._customizations

    @property
    def click_sync_service(self):
        return self._click_sync.service if self._click_sync is not None else None

    @property
    def ghost_cursor_controller(self):
        if self._click_sync is None:
            return None
        return self._click_sync.ghost_cursor_controller

    def set_toon_capture_sink(self, sink) -> None:
        """``sink(pid, name, dna, *, laff, max_laff, species, accent)`` receives
        each toon the game APIs report, for the launcher's recent toons."""
        self._toon_capture_sink = sink

    # ── What InputService reads (any thread) ───────────────────────────────

    def _get_enabled_toons(self):
        return self._slot_enabled

    def _get_movement_modes(self):
        return self._slot_modes

    def _get_key_event_queue(self):
        return self._key_event_queue

    def _get_keymap_assignments(self):
        return self._slot_assignments

    def _get_chat_handling_mode(self) -> str:
        from utils.settings_keys import (
            CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT,
            normalize_chat_handling_mode,
        )
        if self._settings is None:
            return CHAT_HANDLING_MODE_DEFAULT
        return normalize_chat_handling_mode(
            self._settings.get(CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT))

    def _get_chat_enabled(self):
        """Effective per-slot chat broadcast for the current mode. Called per
        keystroke; cost is one pass over ``MAX_TOONS`` entries."""
        return compute_effective_chat_enabled(
            mode=self._get_chat_handling_mode(),
            raw_chat=self._slot_chat,
            enabled_toons=self._slot_enabled,
            assignments=self._slot_assignments,
        )

    # ── Publishing state ───────────────────────────────────────────────────

    def _snapshot(self, toon: _Toon) -> ToonState:
        return ToonState(
            window_id=toon.window_id, slot=toon.slot, game=toon.game,
            name=toon.name, species=toon.species, dna=toon.dna,
            accent=self._accent(toon), enabled=toon.enabled,
            keep_alive=toon.keep_alive, click_sync=toon.click_sync,
            click_sync_supported=(self.click_sync_service is not None
                                  and click_sync_supports_game(toon.game)),
            keyset_id=toon.keyset_id, counters_locked=toon.counters_locked,
            beans=toon.beans, bank=toon.bank, tokens=toon.tokens,
            laff=toon.laff, max_laff=toon.max_laff,
        )

    def _accent(self, toon: _Toon) -> str:
        """The toon's own colour: the user's choice, else the colour the game
        reports, else the game's brand colour."""
        if toon.name:
            try:
                chosen = self._customizations.get(toon.game, toon.name).get("accent")
            except Exception:  # noqa: BLE001
                chosen = None
            chosen = _hex_colour(chosen)
            if chosen:
                return chosen
        reported = _hex_colour(toon.color)
        if reported:
            return reported
        return GAME_ACCENTS.get(toon.game, GAME_ACCENTS[GAME_TTR])

    def _publish(self, structure_changed: bool = False) -> None:
        """Bring everything derived from the records up to date, then announce
        what changed: ``toons_changed`` once when the set or order of toons
        changed, and ``toon_changed`` once per toon whose other fields did."""
        self._rebuild_slot_views()
        self._reconcile_click_sync()
        self._sync_keep_alive_engine()
        changed = []
        for wid in self._order:
            toon = self._toons[wid]
            new = self._snapshot(toon)
            old = toon.state
            toon.state = new
            if old is None:
                structure_changed = True
            elif new != old:
                if new.slot != old.slot:
                    structure_changed = True
                if replace(new, slot=old.slot) != old:
                    changed.append(wid)
        if structure_changed:
            self.toons_changed.emit()
        for wid in changed:
            self.toon_changed.emit(wid)

    def _rebuild_slot_views(self) -> None:
        enabled = [False] * MAX_TOONS
        chat = [True] * MAX_TOONS
        assignments = [0] * MAX_TOONS
        modes = [self._keysets.name(GAME_TTR, self._keysets.lowest_visible(GAME_TTR))] * MAX_TOONS
        keep_alive = [False] * MAX_TOONS
        rapid_fire = [False] * MAX_TOONS
        for wid in self._order:
            toon = self._toons[wid]
            slot = toon.slot
            enabled[slot] = self._running and toon.enabled
            chat[slot] = toon.chat
            assignments[slot] = self._keysets.index(toon.game, toon.keyset_id)
            modes[slot] = self._keysets.name(toon.game, toon.keyset_id)
            keep_alive[slot] = toon.keep_alive
            rapid_fire[slot] = toon.rapid_fire and toon.keep_alive
        self._slot_enabled = enabled
        self._slot_chat = chat
        self._slot_assignments = assignments
        self._slot_modes = modes
        self._slot_keep_alive = keep_alive
        self._slot_rapid_fire = rapid_fire

    def _label(self, toon: _Toon) -> str:
        name = toon.name or f"Toon {toon.slot + 1}"
        return f"{name} (slot {toon.slot + 1})"

    def _log(self, msg: str, level: str | None = None) -> None:
        if self._logger:
            self._logger.append_log(msg, level=level)
        else:
            print(msg)

    @Slot(str)
    def _on_input_log(self, msg: str) -> None:
        self._log(msg)

    # ── Windows ────────────────────────────────────────────────────────────

    def _game_of(self, window_id: str) -> str:
        games = getattr(self._window_manager, "window_games", None) or {}
        game = games.get(window_id)
        if game not in (GAME_TTR, GAME_CC):
            try:
                from utils.game_registry import GameRegistry
                game = GameRegistry.instance().get_game_for_window(str(window_id))
            except Exception:  # noqa: BLE001
                game = None
        return game if game in (GAME_TTR, GAME_CC) else GAME_TTR

    @Slot(list)
    def _on_window_ids(self, window_ids) -> None:
        if self._shut_down:
            return
        all_ids = [str(w) for w in window_ids]
        ids = all_ids[:MAX_TOONS]
        structure_changed = ids != self._order
        if structure_changed:
            for wid in self._order:
                if wid not in ids:
                    del self._toons[wid]
                    self._last_captured.pop(wid, None)
                    self._render_seen.pop(wid, None)
            for slot, wid in enumerate(ids):
                toon = self._toons.get(wid)
                if toon is None:
                    self._toons[wid] = self._new_toon(wid, slot)
                else:
                    toon.slot = slot
            self._order = ids
            invalidate_port_to_wid_cache()
            clear_stale_names(all_ids)
        for wid in ids:
            # The game of a window can resolve after the window is first seen.
            toon = self._toons[wid]
            game = self._game_of(wid)
            if game != toon.game:
                toon.game = game
                toon.clear_game_data()
                toon.named_as = None
                self._settle_keyset(toon)
                if not click_sync_supports_game(game):
                    toon.click_sync = False
        self._publish(structure_changed)
        service = self.click_sync_service
        if service is not None:
            service.recompute()
        self._schedule_fetch()

    def _new_toon(self, window_id: str, slot: int) -> _Toon:
        game = self._game_of(window_id)
        toon = _Toon(window_id, slot, game, self._keysets.lowest_visible(game))
        carried = self._refresh_carry.pop(window_id, None)
        if carried is not None:
            keyset_id, counters_locked = carried
            if self._keysets.usable(game, keyset_id):
                toon.keyset_id = keyset_id
                toon.keyset_chosen = True
            toon.counters_locked = counters_locked
            toon.counters_chosen = True
        return toon

    @Slot()
    def _on_window_geometry(self) -> None:
        # A resize does not change the window list; the geometry signal drives
        # click sync's live aspect re-check (mismatch pause and recovery).
        service = self.click_sync_service
        if service is not None and not self._shut_down:
            service.recompute()

    # ── Keysets and remembered choices ─────────────────────────────────────

    def _settle_keyset(self, toon: _Toon) -> None:
        """A toon never sits on a keyset that is gone or hidden."""
        if not self._keysets.usable(toon.game, toon.keyset_id):
            toon.keyset_id = self._keysets.lowest_visible(toon.game)

    @Slot()
    def _on_keymaps_changed(self) -> None:
        if self._shut_down:
            return
        for wid in self._order:
            self._settle_keyset(self._toons[wid])
        self._publish()

    def _adopt_identity(self, toon: _Toon) -> None:
        """The toon just got a (new) name: bring in what was remembered for
        it, or remember what the user already chose on this window."""
        identity = toon_identity(toon.game, toon.name)
        if identity is None:
            return
        stored = self._prefs.get(identity)
        if toon.keyset_chosen:
            self._prefs.update(identity, keyset_id=toon.keyset_id)
        else:
            keyset_id = stored.get("keyset_id")
            if isinstance(keyset_id, str) and self._keysets.usable(toon.game, keyset_id):
                toon.keyset_id = keyset_id
        if toon.counters_chosen:
            self._prefs.update(identity, counters_locked=toon.counters_locked)
        elif "counters_locked" in stored:
            toon.counters_locked = bool(stored["counters_locked"])

    def _set_name(self, toon: _Toon, name: str | None) -> None:
        if name == toon.name:
            return
        toon.name = name
        if name is None or name == toon.named_as:
            # The name dropping out (a missed poll, the pick-a-toon screen)
            # and coming back changes nothing the user set.
            return
        if toon.named_as is not None:
            # A different toon in the same window: this window's earlier
            # choices belonged to the previous one.
            toon.keyset_chosen = False
            toon.counters_chosen = False
            toon.counters_locked = False
            toon.keyset_id = self._keysets.lowest_visible(toon.game)
        toon.named_as = name
        self._adopt_identity(toon)

    # ── Running ────────────────────────────────────────────────────────────

    def _set_running(self, running: bool) -> None:
        if running == self._running or self._shut_down:
            return
        self._running = running
        self._apply_click_sync_master()
        self._publish()
        if running:
            self._log("[Service] Multitoon service started.", level="ok")
            self._schedule_fetch()
        else:
            self._log("[Service] Multitoon service stopped.")
        self.running_changed.emit(running)

    def _refresh_is_coalesced(self, now: float) -> bool:
        """True when a refresh asked for at monotonic ``now`` falls inside the
        cooldown of the last accepted one. Otherwise records ``now`` as the new
        origin and returns False."""
        if now - self._last_refresh_monotonic < self.REFRESH_COOLDOWN_S:
            return True
        self._last_refresh_monotonic = now
        return False

    # ── Settings ───────────────────────────────────────────────────────────

    @Slot(str, object)
    def _on_setting_changed(self, key, value) -> None:
        if self._shut_down:
            return
        if key in ("keep_alive_delay", "keep_alive_action"):
            if any(self._slot_keep_alive):
                self._reset_ka_cycle()
            return
        if key == CLICK_SYNC_ENABLED:
            self._apply_click_sync_master()
        if key in (KEEP_ALIVE_MASTER_KEY, KEEP_ALIVE_CONSENT_KEY, CLICK_SYNC_ENABLED):
            keep_alive = self.keep_alive_available()
            click_sync = self.click_sync_available()
            changed = (keep_alive != self._keep_alive_was_available
                       or click_sync != self._click_sync_was_available)
            self._keep_alive_was_available = keep_alive
            self._click_sync_was_available = click_sync
            # Per-toon flags are the user's setup and survive the master
            # switch; only the loop starts or stops.
            self._publish()
            if changed:
                self.features_changed.emit()

    # ── Click sync ─────────────────────────────────────────────────────────

    def _apply_click_sync_master(self) -> None:
        service = self.click_sync_service
        if service is None:
            return
        # Paused while broadcast is stopped; membership is kept either way.
        service.set_enabled(self._running and self.click_sync_available())

    def _reconcile_click_sync(self) -> None:
        """Make the service's slot membership say what the toons say."""
        service = self.click_sync_service
        if service is None:
            return
        wanted = {self._toons[wid].slot for wid in self._order
                  if self._toons[wid].click_sync}
        for slot in sorted(wanted ^ set(service.members())):
            service.toggle_slot(slot)

    def _records_are_current(self) -> bool:
        try:
            live = [str(w) for w in self._window_manager.get_window_ids()][:MAX_TOONS]
        except Exception:  # noqa: BLE001
            return True
        return live == self._order

    @Slot(object)
    def _on_click_sync_states(self, states) -> None:
        self._click_sync_states = dict(states)
        self._click_sync_error = None
        if not self._records_are_current():
            # The window list moved under us; the pending window update
            # re-derives membership from the toons.
            return
        # The service drops a member whose window it can no longer drive.
        members = self.click_sync_service.members()
        dropped = [wid for wid in self._order
                   if self._toons[wid].click_sync
                   and self._toons[wid].slot not in members]
        if dropped:
            for wid in dropped:
                self._toons[wid].click_sync = False
            self._publish()

    @Slot(str)
    def _on_click_sync_error(self, message: str) -> None:
        self._click_sync_error = message
        print(f"[ToonSession] click sync error: {message}")

    def click_sync_state(self, window_id: str) -> str:
        """``"off" | "armed" | "active" | "error"`` for that toon: member but
        waiting for a second toon, mirroring, or paused on a problem."""
        toon = self._toons.get(window_id)
        if toon is None:
            return "off"
        state = self._click_sync_states.get(toon.slot, "off")
        return state if state in ("off", "armed", "active", "error") else "off"

    # ── Toon polling ───────────────────────────────────────────────────────

    def _schedule_fetch(self, delay_ms: int | None = None) -> None:
        if not self._activated or self._shut_down or not self._order:
            return
        self._fetch_timer.start(self.FETCH_DELAY_MS if delay_ms is None else max(0, delay_ms))

    @Slot()
    def _fetch_toon_data(self) -> None:
        wids = list(self._order)
        settings = self._settings
        ttr_on = bool(settings and settings.get("enable_companion_app", True))
        cc_on = bool(settings and settings.get("enable_cc_companion_app", True))
        if not wids or not (ttr_on or cc_on):
            return
        request_key = (tuple(wids), ttr_on, cc_on)
        if request_key in self._fetch_inflight:
            return
        self._fetch_inflight.add(request_key)
        self._refresh_gen += 1
        gen = self._refresh_gen
        ttr_wids = [w for w in wids if self._toons[w].game == GAME_TTR]
        cc_wids = [w for w in wids if self._toons[w].game == GAME_CC]

        def _run():
            try:
                if ttr_wids and ttr_on:
                    result = get_toon_names_by_slot(len(ttr_wids), ttr_wids)
                    self._ttr_data_ready.emit((gen, list(ttr_wids), result))
                if cc_wids and cc_on:
                    cc_api.get_toon_data_threaded(
                        len(cc_wids), cc_wids,
                        lambda infos: self._cc_data_ready.emit(
                            (gen, list(cc_wids), list(infos))))
            except Exception as e:  # noqa: BLE001
                print(f"[ToonSession] toon data fetch failed: {e}")
            finally:
                self._fetch_inflight.discard(request_key)

        threading.Thread(target=_run, daemon=True).start()

    @Slot(object)
    def _apply_ttr_data(self, payload) -> None:
        gen, wids, result = payload
        if gen != self._refresh_gen or self._shut_down:
            return
        names, styles, colors, laffs, max_laffs, beans, bank, tokens = result

        def at(values, i):
            return values[i] if values is not None and i < len(values) else None

        from utils.ttr_dna import parse_dna
        for i, wid in enumerate(wids):
            toon = self._toons.get(wid)
            if toon is None or toon.game != GAME_TTR or i >= len(names):
                continue
            name, dna = at(names, i), at(styles, i)
            species, _ = parse_dna(dna or "")
            self._set_name(toon, name)
            toon.dna = dna
            toon.species = species.lower() if species else None
            toon.color = at(colors, i)
            toon.laff, toon.max_laff = at(laffs, i), at(max_laffs, i)
            toon.beans, toon.bank, toon.tokens = at(beans, i), at(bank, i), at(tokens, i)
            self._capture(toon, laff=toon.laff, max_laff=toon.max_laff,
                          species=species, accent=toon.color)
        self._publish()

    @Slot(object)
    def _apply_cc_data(self, payload) -> None:
        gen, wids, infos = payload
        if gen != self._refresh_gen or self._shut_down:
            return
        from utils.color_math import rgb_floats_to_hex
        for i, wid in enumerate(wids):
            toon = self._toons.get(wid)
            if toon is None or toon.game != GAME_CC:
                continue
            info = infos[i] if i < len(infos) else None
            if info is None or info.name is None:
                self._set_name(toon, None)
                toon.clear_game_data()
                continue
            self._set_name(toon, info.name)
            toon.species = info.species_name.lower() if info.species_name else None
            toon.color = rgb_floats_to_hex(info.dna_colors[0]) if info.dna_colors else None
            # The Corporate Clash log exposes no DNA string and no counters.
            toon.dna = None
            toon.beans = toon.bank = toon.tokens = toon.laff = toon.max_laff = None
            self._capture(toon, species=info.species_name, accent=toon.color)
        self._publish()

    def _capture(self, toon: _Toon, *, laff=None, max_laff=None,
                 species=None, accent=None) -> None:
        """Hand a resolved toon to the render cache and the launcher."""
        wid, name, dna = toon.window_id, toon.name, toon.dna or ""
        if name and dna and self._render_seen.get(wid) != (name, dna):
            # A toon's name and DNA are all the render cache needs; it must
            # not depend on whether this app launched the window.
            try:
                from utils.toon_renders import ToonRenders
                ToonRenders.instance().discovered(toon.game, name, dna)
                self._render_seen[wid] = (name, dna)
            except Exception as exc:  # noqa: BLE001
                print(f"[ToonRenders] discovery hook failed: {exc}")
        if not self._toon_capture_sink or not name:
            return
        from utils.toon_capture_bridge import toon_changed
        if not toon_changed(self._last_captured, wid, name, dna, laff):
            return      # unchanged since the last poll: skip the pid lookup
        from utils.game_registry import GameRegistry
        pid = GameRegistry.pid_for_window(wid)   # host pid, matches the launch
        if pid is not None:
            self._toon_capture_sink(pid, name, dna, laff=laff, max_laff=max_laff,
                                    species=species, accent=accent)
            self._last_captured[wid] = (name, dna, laff)

    # ── Profiles ───────────────────────────────────────────────────────────

    def _autosave_active_profile(self) -> None:
        """Persist the live state to the active profile, if one is."""
        manager = self._profile_manager
        if self._active_profile < 0 or not manager:
            return
        enabled = [False] * MAX_TOONS
        for wid in self._order:
            enabled[self._toons[wid].slot] = self._toons[wid].enabled
        manager.save_profile(
            self._active_profile, enabled, list(self._slot_modes),
            keep_alive=list(self._slot_keep_alive),
            rapid_fire=list(self._slot_rapid_fire),
        )

    # ── Keep-alive engine ──────────────────────────────────────────────────

    def _sync_keep_alive_engine(self) -> None:
        """The loop runs exactly while broadcast is on, the feature is
        available and at least one toon has keep-alive on."""
        wanted = (self._running and not self._shut_down
                  and any(self._slot_keep_alive)
                  and self.keep_alive_available())
        if wanted and not self._keep_alive_running:
            self._start_keep_alive()
        elif not wanted and self._keep_alive_running:
            self._stop_keep_alive()
        elif wanted:
            self._ka_cycle_event.set()      # re-read who fires, and how often

    def _reset_ka_cycle(self) -> None:
        self._ka_cycle_start = time.monotonic()
        self._ka_cycle_event.set()

    def _start_keep_alive(self) -> None:
        if self._keep_alive_running:
            return
        self._keep_alive_running = True
        self._ka_cycle_start = time.monotonic()
        self._ka_cycle_event.clear()
        self._acquire_sleep_inhibitor()
        self._keep_alive_thread = threading.Thread(
            target=self._run_keep_alive_loop, daemon=True)
        self._keep_alive_thread.start()

    def _stop_keep_alive(self) -> None:
        if not self._keep_alive_running:
            return
        self._keep_alive_running = False
        self._ka_cycle_start = 0.0
        self._ka_cycle_event.set()          # wake the thread so it exits
        thread = self._keep_alive_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._release_sleep_inhibitor()

    def _run_keep_alive_loop(self) -> None:
        try:
            last_normal_fire = 0.0
            last_rapid_fire = 0.0
            while self._keep_alive_running:
                # With a rapid-fire toon the loop wakes every second;
                # otherwise it sleeps the configured delay.
                if any(self._slot_rapid_fire):
                    timeout = 1.0
                else:
                    timeout = keep_alive_delay_seconds(self._settings)
                self._ka_cycle_event.wait(timeout=timeout)
                if self._ka_cycle_event.is_set():
                    self._ka_cycle_event.clear()
                if not self._keep_alive_running:
                    break
                # Re-check the gate: if the user opted out while the loop
                # slept, skip the cycle. The stop follows shortly; this bounds
                # a leak to nothing.
                if not (self._running and self.keep_alive_available()):
                    continue

                now = time.monotonic()
                normal_delay = keep_alive_delay_seconds(self._settings)
                keep_alive = self._slot_keep_alive
                rapid_fire = self._slot_rapid_fire
                fire = set()
                if now - last_rapid_fire >= 1.0:
                    rapid = [i for i, on in enumerate(rapid_fire) if on and keep_alive[i]]
                    fire.update(rapid)
                    if rapid:
                        last_rapid_fire = now
                if now - last_normal_fire >= normal_delay or last_normal_fire == 0.0:
                    normal = [i for i, on in enumerate(keep_alive) if on and not rapid_fire[i]]
                    fire.update(normal)
                    if normal:
                        last_normal_fire = now
                        self._ka_cycle_start = now
                if not fire:
                    continue

                action = (self._settings.get("keep_alive_action", "jump")
                          if self._settings else "jump")
                fired = dispatch_keep_alive_cycle(
                    action=action,
                    fire_toons=sorted(fire),
                    window_manager=self._window_manager,
                    keymap_manager=self._keymap_manager,
                    input_service=self._input_service,
                )
                label = KEEP_ALIVE_ACTION_LABELS.get(action, action)
                if fired > 0:
                    self._log(f"[KeepAlive] Sent '{label}' to {fired} toon(s)")
                else:
                    self._log(f"[KeepAlive] no toons matched action '{action}' this cycle")
        except Exception as e:  # noqa: BLE001
            self._log(f"[KeepAlive] Error: {e}")

    # ── Sleep inhibitor ────────────────────────────────────────────────────

    def _acquire_sleep_inhibitor(self) -> None:
        """Acquire the OS sleep/idle inhibitor off the GUI thread.

        acquire() can block for over a second (it shells out and polls), so
        it runs on a worker. A generation number makes a late result from a
        worker superseded by a release or re-acquire a no-op.
        """
        from services._inhibit_worker import InhibitAcquireWorker
        # Never drop the last reference to a running QThread: it aborts with
        # "Destroyed while thread is still running".
        previous = self._inhibit_worker
        if previous is not None and previous.isRunning():
            previous.wait(5000)
            if previous.isRunning():
                self._retired_workers = [
                    w for w in self._retired_workers if w.isRunning()] + [previous]
        self._inhibit_gen += 1
        gen = self._inhibit_gen
        worker = InhibitAcquireWorker(self._sleep_inhibitor)
        worker.status_ready.connect(
            lambda status, g=gen: self._on_inhibit_status(g, status))
        self._inhibit_worker = worker
        worker.start()

    def _on_inhibit_status(self, gen, status) -> None:
        if gen != self._inhibit_gen:
            return      # superseded
        if getattr(status, "sleep_blocked", False):
            self._log(f"[KeepAlive] Sleep inhibitor verified ({status.method}).")
        else:
            self._log("[KeepAlive] Could not verify sleep inhibitor; "
                      "the machine may sleep.", level="warn")
        self.keep_alive_inhibit_status.emit(status)

    def _release_sleep_inhibitor(self) -> None:
        """Release the inhibitor and make any in-flight acquire result void."""
        self._inhibit_gen += 1
        worker = self._inhibit_worker
        if worker is not None and worker.isRunning():
            worker.wait(2000)       # let a fast acquire finish first
        # Unconditional: an acquire that outran the wait still ends up
        # holding something, and release() blocks on the inhibitor's own lock
        # until that acquire completes, so nothing is leaked. It is a no-op
        # when nothing is held.
        self._sleep_inhibitor.release()
        self._log("[KeepAlive] Sleep inhibitor released.")
        if worker is not None and not worker.isRunning():
            self._inhibit_worker = None
