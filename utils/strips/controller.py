"""One strip per toon, driven by a ToonSession.

The controller owns no toon state. It turns what the session and the keymap
manager say into a StripModel per window, keeps a strip surface on each
window through the follower, and turns clicks back into session calls.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from utils import settings_keys
from utils.strips import layout as L
from utils.strips import tokens
from utils.strips.follow import StripFollower
from utils.strips.model import StripModel

class KeysetView:
    """The keysets of a game as a strip needs them: every set has an id, a
    NUMBER (its position + 1, which is also its colour) and may be hidden.
    The one place that maps between the session's keyset ids and the numbers
    on the buttons."""

    def __init__(self, keymap_manager=None, fixed_ids: dict | None = None) -> None:
        """`fixed_ids` ({game: [id, ...]}, none hidden) stands in where there
        is no keymap manager: demos and tests on the fake session."""
        self._km = keymap_manager
        self._fixed = {g: [str(i) for i in ids]
                       for g, ids in (fixed_ids or {}).items()}

    def entries(self, game: str) -> list[tuple[str, int, bool]]:
        """(id, number, hidden) for every set of `game`, in order."""
        if self._km is None:
            return [(set_id, i + 1, False)
                    for i, set_id in enumerate(self._fixed.get(game, ()))]
        try:
            sets = self._km.get_sets(game) or []
        except Exception:
            sets = []
        return [(str(entry.get("id")), index + 1, entry.get("hidden") is True)
                for index, entry in enumerate(sets) if entry.get("id")]

    def visible_numbers(self, game: str) -> tuple[int, ...]:
        return tuple(n for _id, n, hidden in self.entries(game) if not hidden)

    def hidden_numbers(self, game: str) -> tuple[int, ...]:
        return tuple(n for _id, n, hidden in self.entries(game) if hidden)

    def number_for(self, game: str, keyset_id: str) -> int:
        """Number of the set with this id; 0 when the game has no such set."""
        for set_id, number, _hidden in self.entries(game):
            if set_id == keyset_id:
                return number
        return 0

    def id_for(self, game: str, number: int) -> str | None:
        for set_id, n, _hidden in self.entries(game):
            if n == number:
                return set_id
        return None

    def can_add(self, game: str) -> bool:
        """True while the game has room for another set (and there is a
        keymap manager to add it to)."""
        return self._km is not None and len(self.entries(game)) < tokens.MAX_SETS


def build_model(toon, *, home: bool, running: bool,
                keep_alive_available: bool, click_sync_available: bool,
                keysets: KeysetView, portrait=None,
                home_open: bool = False) -> StripModel:
    """What one toon's strip shows. Pure: same inputs, same model."""
    hidden = keysets.hidden_numbers(toon.game)
    return StripModel(
        name=toon.name or f"Toon {toon.slot + 1}",
        accent=toon.accent,
        game=toon.game,
        species=toon.species,
        portrait=portrait,
        enabled=bool(toon.enabled),
        running=bool(running),
        # A feature that is off app-wide has no block at all. The toon keeps
        # its own flag underneath for when the feature comes back.
        keep_alive=bool(toon.keep_alive) if keep_alive_available else None,
        click_sync=(bool(toon.click_sync)
                    if click_sync_available and toon.click_sync_supported
                    else None),
        keysets=keysets.visible_numbers(toon.game),
        active=keysets.number_for(toon.game, toon.keyset_id),
        show_add=keysets.can_add(toon.game) or bool(hidden),
        hidden_sets=bool(hidden),
        home=home,
        home_open=home and home_open,
    )


class StripController(QObject):
    # For the popovers and the home block (later milestones); window id first.
    context_requested = Signal(str, str, int)   # window id, block kind, number
    add_menu_requested = Signal(str)            # + pressed while sets are hidden
    home_clicked = Signal(str)
    identity_hovered = Signal(str, bool)
    home_moved = Signal(str)                    # window id now carrying the home block
    _keymaps_changed = Signal()
    _style_changed = Signal(str)

    def __init__(self, session, follower: StripFollower | None = None,
                 keymap_manager=None, settings_manager=None,
                 style: str | None = None, keyset_ids: dict | None = None,
                 portrait_fn: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._keymap_manager = keymap_manager
        self._settings = settings_manager
        self._keysets = KeysetView(keymap_manager, keyset_ids)
        self._portrait_fn = portrait_fn
        if style is None:
            style = self._style_from_settings()
        self._follower = follower if follower is not None else StripFollower(
            style=style, parent=self)
        self._follower.set_style(style)
        self._wired: set[str] = set()
        self._home_wid: str | None = None
        self._home_open = False
        self._started = False

        session.toons_changed.connect(self._sync)
        session.toon_changed.connect(self._refresh_one)
        session.running_changed.connect(lambda _on: self._refresh_all())
        session.features_changed.connect(self._refresh_all)
        # The keymap manager calls back on whatever thread edited it.
        self._keymaps_changed.connect(self._refresh_all)
        if keymap_manager is not None:
            keymap_manager.on_change(self._keymaps_changed.emit)
        self._style_changed.connect(self.set_style)
        if settings_manager is not None:
            settings_manager.on_change(self._on_setting)

    # -- lifecycle ----------------------------------------------------------

    @property
    def follower(self) -> StripFollower:
        return self._follower

    @property
    def keysets(self) -> KeysetView:
        return self._keysets

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._sync()
        self._follower.start()

    def shutdown(self) -> None:
        self._started = False
        self._follower.shutdown()
        self._wired.clear()
        self._home_wid = None

    def _style_from_settings(self) -> str:
        if self._settings is None:
            return tokens.NEON
        try:
            return tokens.style_for(self._settings.get(
                settings_keys.FLOAT_STRIP_STYLE,
                settings_keys.FLOAT_STRIP_STYLE_DEFAULT)).name
        except Exception:
            return tokens.NEON

    def _on_setting(self, key, value) -> None:
        if key == settings_keys.FLOAT_STRIP_STYLE:
            self._style_changed.emit(tokens.style_for(value).name)

    def set_style(self, name: str) -> None:
        self._follower.set_style(name)

    def set_home_open(self, is_open: bool) -> None:
        """The quick menu opened or closed: the home block shows its ring."""
        if bool(is_open) != self._home_open:
            self._home_open = bool(is_open)
            if self._home_wid is not None:
                self._refresh_one(self._home_wid)

    def home_window(self) -> str | None:
        return self._home_wid

    # -- session -> strips --------------------------------------------------

    def _sync(self) -> None:
        """A toon appeared, vanished or changed slot."""
        if not self._started:
            return
        toons = self._session.toons()
        wanted = {t.window_id for t in toons}
        for wid in list(self._follower.surfaces()):
            if wid not in wanted:
                self._follower.remove(wid)
                self._wired.discard(wid)
        for toon in toons:
            surface = self._follower.add(toon.window_id)
            if toon.window_id not in self._wired:
                self._wired.add(toon.window_id)
                self._wire(toon.window_id, surface)
        # Toon 1 is the lowest slot with a live window: it carries the home
        # block, and hands it on when its window closes.
        home = toons[0].window_id if toons else None
        if home != self._home_wid:
            self._home_wid = home
            if home is not None:
                self.home_moved.emit(home)
        self._refresh_all()

    def _wire(self, wid: str, surface) -> None:
        strip = surface.strip
        strip.clicked.connect(lambda kind, n, wid=wid: self._on_click(wid, kind, n))
        strip.context_requested.connect(
            lambda kind, n, wid=wid: self.context_requested.emit(wid, kind, n))
        strip.hover_changed.connect(
            lambda kind, _n, wid=wid: self.identity_hovered.emit(
                wid, kind in (L.PORTRAIT, L.NAME)))

    def model_for(self, window_id: str) -> StripModel | None:
        toon = self._session.toon(window_id)
        if toon is None:
            return None
        portrait = None
        if self._portrait_fn is not None:
            try:
                portrait = self._portrait_fn(toon)
            except Exception:
                portrait = None
        return build_model(
            toon,
            home=window_id == self._home_wid,
            running=self._session.is_running(),
            keep_alive_available=self._session.keep_alive_available(),
            click_sync_available=self._session.click_sync_available(),
            keysets=self._keysets,
            portrait=portrait,
            home_open=self._home_open,
        )

    def _refresh_one(self, window_id: str) -> None:
        surface = self._follower.surface(window_id)
        model = self.model_for(window_id)
        if surface is not None and model is not None:
            surface.set_model(model)

    def _refresh_all(self) -> None:
        for wid in self._follower.surfaces():
            self._refresh_one(wid)

    # -- strips -> session --------------------------------------------------

    def _on_click(self, wid: str, kind: str, number: int) -> None:
        toon = self._session.toon(wid)
        if toon is None:
            return
        if kind == L.KEYSET:
            set_id = self._keysets.id_for(toon.game, number)
            if set_id is not None:
                self._session.set_keyset(wid, set_id)
        elif kind == L.ENABLE:
            self._session.set_enabled(wid, not toon.enabled)
        elif kind == L.KEEP_ALIVE:
            self._session.set_keep_alive(wid, not toon.keep_alive)
        elif kind == L.CLICK_SYNC:
            self._session.set_click_sync(wid, not toon.click_sync)
        elif kind == L.ADD:
            if self._keysets.hidden_numbers(toon.game):
                self.add_menu_requested.emit(wid)
            elif self._keymap_manager is not None:
                self._keymap_manager.add_set(toon.game)
        elif kind == L.HOME:
            self.home_clicked.emit(wid)
