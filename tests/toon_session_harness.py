"""Stand-ins for everything a ToonSession talks to, for the session suites.

Nothing here opens a display connection, a socket or a thread: the session
under test is the only real object.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from services.click_sync_wiring import click_sync_slot_window
from services.toon_prefs import ToonPrefs
from services.toon_session import ToonSession


class FakeSettings:
    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self._callbacks = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        for cb in list(self._callbacks):
            cb(key, value)

    def on_change(self, callback):
        self._callbacks.append(callback)


class FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.window_games = {}
        self.geometry = {}
        self.active = None
        self.calls = []

    def set_windows(self, ids, games=None):
        """The poll loop found this window list."""
        self.ttr_window_ids = list(ids)
        games = games or {}
        self.window_games = {w: games.get(w, "ttr") for w in ids}
        self.window_ids_updated.emit(list(ids))

    def get_window_ids(self):
        return list(self.ttr_window_ids)

    def get_window_geometry(self, wid):
        return self.geometry.get(wid, (0, 0, 800, 600))

    def get_active_window(self):
        return self.active

    def enable_detection(self):
        self.calls.append("enable_detection")

    def disable_detection(self):
        self.calls.append("disable_detection")

    def clear_window_ids(self):
        self.calls.append("clear_window_ids")
        self.ttr_window_ids = []
        self.window_games = {}
        self.window_ids_updated.emit([])


class StubInputService(QObject):
    input_log = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.calls = []
        self.sent = []
        self.skip = set()

    def start(self):
        self.calls.append("start")

    def stop(self, wait=False):
        self.calls.append("stop")

    def shutdown(self):
        self.calls.append("shutdown")

    def send_keep_alive_to_window(self, wid, key, modifiers=None):
        self.sent.append((wid, key))

    def keep_alive_skip_window(self, wid):
        return wid in self.skip


class StubClickSyncService(QObject):
    """Slot membership with the real service's eviction rule and nothing else."""

    slot_states_changed = Signal(object)
    service_error = Signal(str)

    def __init__(self, window_manager):
        super().__init__()
        self._wm = window_manager
        self._members = set()
        self.enabled = False
        self.calls = []
        self._states = {s: "off" for s in range(4)}

    def set_enabled(self, enabled):
        self.calls.append(("set_enabled", bool(enabled)))
        self.enabled = bool(enabled)
        self.recompute()

    def toggle_slot(self, slot):
        self.calls.append(("toggle_slot", slot))
        if slot in self._members:
            self._members.discard(slot)
            member = False
        else:
            self._members.add(slot)
            member = True
        self.recompute()
        return member

    def members(self):
        return frozenset(self._members)

    def recompute(self):
        self.calls.append(("recompute",))
        if self.enabled:
            self._members = {
                s for s in self._members
                if click_sync_slot_window(self._wm, s) is not None}
            state = "active" if len(self._members) >= 2 else "armed"
            states = {s: (state if s in self._members else "off") for s in range(4)}
        else:
            states = {s: "off" for s in range(4)}
        if states != self._states:
            self._states = states
            self.slot_states_changed.emit(dict(states))

    def shutdown(self):
        self.calls.append(("shutdown",))


class FakeInhibitor:
    def __init__(self):
        self.calls = []
        self.status = SimpleNamespace(sleep_blocked=True, method="fake")

    def acquire(self):
        self.calls.append("acquire")

    def release(self):
        self.calls.append("release")


class FakeCustomizations:
    def __init__(self):
        self.entries = {}

    def get(self, game, name):
        return dict(self.entries.get((game, name), {}))


class FakeKeymaps:
    """Sets as plain dicts, with the change callbacks KeymapManager has."""

    def __init__(self, ttr=None, cc=None):
        self.sets = {
            "ttr": ttr if ttr is not None else [
                {"name": "Default"}, {"name": "Arrows"}, {"name": "Third"}],
            "cc": cc if cc is not None else [{"name": "Default"}, {"name": "Clash 2"}],
        }
        self._listeners = []

    def get_sets(self, game):
        return [dict(s) for s in self.sets.get(game, [])]

    def get_key_for_action(self, game, set_index, action):
        return {"jump": "space", "book": "Alt_L", "forward": "Up"}.get(action)

    def on_change(self, callback):
        self._listeners.append(callback)

    def changed(self):
        for cb in list(self._listeners):
            cb()


class FakeProfiles:
    def __init__(self, profiles=None):
        self.profiles = profiles or {}
        self.saved = []

    def get_profile(self, index):
        return self.profiles[index]

    def get_name(self, index):
        return f"Profile {index + 1}"

    def save_profile(self, index, enabled_toons, movement_modes,
                     keep_alive=None, rapid_fire=None):
        self.saved.append((index, list(enabled_toons), list(movement_modes),
                           list(keep_alive), list(rapid_fire)))


def profile(enabled, modes=None, keep_alive=None, rapid_fire=None):
    return SimpleNamespace(
        enabled_toons=list(enabled),
        movement_modes=list(modes or ["Default"] * 4),
        keep_alive=list(keep_alive or [False] * 4),
        rapid_fire=list(rapid_fire or [False] * 4),
    )


class Spy:
    """Every emission of the session's public signals, in order."""

    def __init__(self, session):
        self.events = []
        session.toons_changed.connect(lambda: self.events.append(("toons",)))
        session.toon_changed.connect(lambda wid: self.events.append(("toon", wid)))
        session.running_changed.connect(lambda on: self.events.append(("running", on)))
        session.features_changed.connect(lambda: self.events.append(("features",)))


KEEP_ALIVE_ON = {"keep_alive_enabled": True, "keep_alive_consent_acknowledged": True}


class Rig:
    """A ToonSession over stand-ins. Not activated unless asked: no thread,
    no timer, no window detection."""

    def __init__(self, tmp_path, *, settings=None, windows=(), games=None,
                 click_sync=True, activate=False, keymaps=None, profiles=None):
        self.settings = FakeSettings(settings)
        self.wm = FakeWindowManager()
        if windows:
            self.wm.ttr_window_ids = list(windows)
            self.wm.window_games = {w: (games or {}).get(w, "ttr") for w in windows}
        self.keymaps = keymaps if keymaps is not None else FakeKeymaps()
        self.profiles = profiles if profiles is not None else FakeProfiles()
        self.customizations = FakeCustomizations()
        self.prefs_path = str(tmp_path / "toon_session.json")
        self.prefs = ToonPrefs(self.prefs_path)
        self.inhibitor = FakeInhibitor()
        self.logs = []
        self.click_sync = StubClickSyncService(self.wm) if click_sync else None
        wiring = None
        if self.click_sync is not None:
            wiring = SimpleNamespace(
                service=self.click_sync, backend=None, ghost_cursor_controller=None,
                shutdown=self.click_sync.shutdown)
        self.session = ToonSession(
            self.wm,
            settings_manager=self.settings,
            keymap_manager=self.keymaps,
            profile_manager=self.profiles,
            logger=SimpleNamespace(
                append_log=lambda msg, level=None: self.logs.append(msg)),
            customizations=self.customizations,
            prefs=self.prefs,
            sleep_inhibitor=self.inhibitor,
            input_service_factory=StubInputService,
            click_sync_builder=lambda session: wiring,
            activate=activate,
        )
        self.input = self.session.input_service
        self.spy = Spy(self.session)

    # What the game API would report, pushed straight into the apply step.

    def ttr(self, wid, name, *, dna="", color=None, laff=None, max_laff=None,
            beans=None, bank=None, tokens=None):
        result = ([name], [dna], [color], [laff], [max_laff], [beans], [bank], [tokens])
        self.session._apply_ttr_data((self.session._refresh_gen, [wid], result))

    def cc(self, wid, info):
        self.session._apply_cc_data((self.session._refresh_gen, [wid], [info]))

    def close(self):
        self.session.shutdown()
