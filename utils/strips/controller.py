"""One strip per toon, driven by a ToonSession.

The controller owns no toon state. It turns what the session and the keymap
manager say into a StripModel per window, keeps a strip surface on each
window through the follower, and turns clicks back into session calls.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from utils import cartoonival, logical_actions, settings_keys
from utils.strips import layout as L
from utils.strips import tokens
from utils.strips.follow import StripFollower
from utils.strips.model import StripModel
from utils.strips.popovers import editor as editor_mod
from utils.strips.popovers.counters import CountersModel
from utils.strips.launcher_port import read_accounts
from utils.strips.popovers import home as home_mod
from utils.strips.popovers.editor import EditorModel, KeysetEditor
from utils.strips.popovers.home import HomePanel
from utils.strips.popovers.placement import LEFT
from utils.strips.popovers.manager import IDENTITY, StripPopovers
from utils.strips.popovers.menu import MenuItem

# Where the shell should take the user when a strip asks for the window.
WINDOW_MAIN = "main"
WINDOW_SETTINGS = "settings"
WINDOW_LAUNCHER = "launcher"

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

    def entry_for_number(self, game: str, number: int):
        for entry in self.entries(game):
            if entry[1] == number:
                return entry
        return None

    def can_add(self, game: str) -> bool:
        """True while the game has room for another set (and there is a
        keymap manager to add it to)."""
        return self._km is not None and len(self.entries(game)) < tokens.MAX_SETS


def build_model(toon, *, home: bool, running: bool,
                keep_alive_available: bool, click_sync_available: bool,
                keysets: KeysetView, portrait=None,
                home_open: bool = False, click_sync_state: str = "",
                click_sync_error: str = "") -> StripModel:
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
        click_sync_state=click_sync_state,
        click_sync_error=click_sync_error if click_sync_state == "error" else "",
        keysets=keysets.visible_numbers(toon.game),
        active=keysets.number_for(toon.game, toon.keyset_id),
        show_add=keysets.can_add(toon.game) or bool(hidden),
        hidden_sets=bool(hidden),
        home=home,
        home_open=home and home_open,
    )


def build_counters(toon, *, collapsed: bool, today=None) -> CountersModel:
    """The counters under one toon's name. The token cell exists only for a
    TTR toon during Cartoonival when the game reported a value."""
    show = cartoonival.show_tokens(toon.game, today, toon.tokens)
    return CountersModel(
        beans=toon.beans, bank=toon.bank,
        tokens=toon.tokens if show else None,
        locked=bool(toon.counters_locked),
        accent=toon.accent,
        # With the name plate collapsed, the name leads the counters.
        name=(toon.name or f"Toon {toon.slot + 1}") if collapsed else "",
    )


def build_editor_model(keymap_manager, game: str, number: int) -> EditorModel | None:
    """What the editor shows for keyset `number` of `game`: its actions in
    the game's own order, their keys, and any key shared by two actions."""
    try:
        sets = keymap_manager.get_sets(game) or []
    except Exception:
        return None
    index = number - 1
    if not 0 <= index < len(sets):
        return None
    entry = sets[index]
    actions = logical_actions.actions_for(game)
    labels = logical_actions.ACTION_LABELS
    binds = tuple((a, entry.get(a) or "") for a in actions)
    by_key: dict[str, list[str]] = {}
    for action, key in binds:
        if key:
            by_key.setdefault(key, []).append(action)
    clashing = [(key, acts) for key, acts in by_key.items() if len(acts) > 1]
    note = ""

    def short(action):
        return editor_mod.action_label(action, labels.get(action, action))

    if clashing:
        key, acts = clashing[0]
        note = (f"{editor_mod.key_name(key)} is used by "
                + " and ".join(short(a) for a in acts[:2]))
    else:
        # The same key meaning different things in two sets is usually an
        # accident too; say so, without marking anything red.
        try:
            cross = keymap_manager.cross_set_conflicts(game)
        except Exception:
            cross = []
        for set_a, act_a, set_b, act_b, key in cross:
            if index in (set_a, set_b):
                other_set, other_act = ((set_b, act_b) if set_a == index
                                        else (set_a, act_a))
                note = (f"{editor_mod.key_name(key)} is {short(other_act)} "
                        f"in keyset {other_set + 1}")
                break
    return EditorModel(
        number=number,
        actions=tuple((a, short(a)) for a in actions),
        binds=binds,
        conflicts=frozenset(a for _key, acts in clashing for a in acts),
        note=note,
    )


class StripController(QObject):
    # What a strip cannot do alone: the shell connects these.
    appearance_requested = Signal(str, str)     # game, toon name: open the looks editor
    open_window_requested = Signal(str)         # WINDOW_MAIN | _SETTINGS | _LAUNCHER
    quit_requested = Signal()                   # the home menu's Quit MultiTool
    home_moved = Signal(str)                    # window id now carrying the home block
    _keymaps_changed = Signal()
    _style_changed = Signal(str)

    def __init__(self, session, follower: StripFollower | None = None,
                 keymap_manager=None, settings_manager=None,
                 style: str | None = None, keyset_ids: dict | None = None,
                 portrait_fn: Callable | None = None,
                 popovers: StripPopovers | None = None,
                 today_fn: Callable | None = None,
                 launcher=None,
                 parent: QObject | None = None) -> None:
        """`launcher` is the compact launcher's source (see
        utils/strips/launcher_port.py); without one "Launch accounts" asks
        the shell for the full launcher instead."""
        super().__init__(parent)
        self._session = session
        self._keymap_manager = keymap_manager
        self._settings = settings_manager
        self._keysets = KeysetView(keymap_manager, keyset_ids)
        self._portrait_fn = portrait_fn
        self._portraits = None
        # With the real session there is a looks store: use the render
        # pipeline the launcher cards use. The fake has none: silhouettes.
        if portrait_fn is None and getattr(session, "customizations", None) is not None:
            from utils.strips.portraits import PortraitProvider
            self._portraits = PortraitProvider(
                customizations=session.customizations, parent=self)
            self._portrait_fn = self._portraits.pixmap
            self._portraits.changed.connect(self._portrait_changed)
        if style is None:
            style = self._style_from_settings()
        self._follower = follower if follower is not None else StripFollower(
            style=style, parent=self)
        self._follower.set_style(style)
        self._today_fn = today_fn
        self._popovers = popovers if popovers is not None else StripPopovers(
            self._follower, parent=self)
        from utils.strips.ghost_clicks import GhostClicks
        self._ghost_clicks = GhostClicks(
            self, getattr(session, "click_sync_service", None), settings_manager,
            parent=self)
        self._launcher = launcher
        if launcher is not None:
            try:
                launcher.changed.connect(self._refresh_home_panel)
            except Exception:
                pass
        self._popovers.opened.connect(self._popover_opened)
        self._popovers.closed.connect(self._popover_closed)
        self._popovers.lock_toggled.connect(self._toggle_lock)
        self._popovers.menu_chosen.connect(self._on_menu)
        self._keymaps_changed.connect(self._refresh_editors)
        self._wired: set[str] = set()
        self._home_wid: str | None = None
        self._home_open = False
        self._started = False

        session.toons_changed.connect(self._sync)
        session.toon_changed.connect(self._refresh_one)
        session.running_changed.connect(lambda _on: self._refresh_all())
        session.running_changed.connect(lambda _on: self._refresh_home_panel())
        session.features_changed.connect(self._refresh_all)
        # Membership of the click-sync group, or its error, changed: any
        # strip's Click Sync block may read differently.
        changed = getattr(session, "click_sync_state_changed", None)
        if changed is not None:
            changed.connect(self._refresh_all)
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

    @property
    def popovers(self) -> StripPopovers:
        return self._popovers

    @property
    def ghost_clicks(self):
        return self._ghost_clicks

    def shutdown(self) -> None:
        self._started = False
        self._popovers.shutdown()
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
        self._popovers.set_style(tokens.style_for(name).name)

    def set_home_open(self, is_open: bool) -> None:
        """The quick menu opened or closed: the home block shows its ring."""
        if bool(is_open) != self._home_open:
            self._home_open = bool(is_open)
            if self._home_wid is not None:
                self._refresh_one(self._home_wid)

    def home_window(self) -> str | None:
        return self._home_wid

    def window_for_slot(self, slot: int) -> str | None:
        """The window id of the toon in a session slot, if it has a strip."""
        for toon in self._session.toons():
            if toon.slot == slot:
                return toon.window_id if self._follower.surface(toon.window_id) else None
        return None

    # -- session -> strips --------------------------------------------------

    def _sync(self) -> None:
        """A toon appeared, vanished or changed slot."""
        if not self._started:
            return
        toons = self._session.toons()
        wanted = {t.window_id for t in toons}
        for wid in list(self._follower.surfaces()):
            if wid not in wanted:
                self._popovers.detach_strip(wid)
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
        self._popovers.attach_strip(wid)
        strip.clicked.connect(lambda kind, n, wid=wid: self._on_click(wid, kind, n))
        strip.context_requested.connect(
            lambda kind, n, wid=wid: self._on_context(wid, kind, n))
        strip.hover_changed.connect(
            lambda kind, _n, wid=wid: self._popovers.set_identity_hover(
                wid, kind in (L.PORTRAIT, L.NAME)))
        # The narrow collapse is decided when the strip is placed, and the
        # counters carry the name once the plate is gone.
        surface.geometry_applied.connect(lambda wid=wid: self._refresh_counters(wid))

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
        state, error = "", ""
        try:
            state = self._session.click_sync_state(window_id) or ""
            error = self._session.click_sync_error() or ""
        except Exception:
            pass
        return build_model(
            toon,
            click_sync_state=state,
            click_sync_error=error,
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
            self._refresh_counters(window_id)

    def counters_for(self, window_id: str) -> CountersModel | None:
        toon = self._session.toon(window_id)
        surface = self._follower.surface(window_id)
        if toon is None or surface is None:
            return None
        collapsed = surface.strip.strip_layout().collapse >= L.NO_NAME
        today = self._today_fn() if self._today_fn is not None else None
        return build_counters(toon, collapsed=collapsed, today=today)

    def _refresh_counters(self, window_id: str) -> None:
        self._popovers.set_counters(window_id, self.counters_for(window_id))

    def _toggle_lock(self, window_id: str) -> None:
        toon = self._session.toon(window_id)
        if toon is not None:
            self._session.set_counters_locked(window_id, not toon.counters_locked)

    def customization_changed(self, game: str | None = None,
                              name: str | None = None) -> None:
        """The looks editor saved (the shell calls this next to the
        session's method of the same name): the pose may have changed, so
        the portrait is looked up again. The accent arrives through the
        session's toon_changed."""
        for toon in self._session.toons():
            if (game is None or toon.game == game) and (name is None or toon.name == name):
                if self._portraits is not None and toon.name:
                    self._portraits.forget(toon.game, toon.name)
                self._refresh_one(toon.window_id)

    def _portrait_changed(self, game: str, name: str) -> None:
        """A render landed for this toon: repaint its strip."""
        for toon in self._session.toons():
            if toon.game == game and toon.name == name:
                self._refresh_one(toon.window_id)

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
            hidden = self._keysets.hidden_numbers(toon.game)
            if hidden:
                items = [MenuItem(f"show:{n}", f"Show keyset {n}") for n in hidden]
                items.append(MenuItem("new", "New keyset",
                                      disabled=not self._keysets.can_add(toon.game)))
                self._popovers.toggle_menu(wid, "add", L.ADD, 0, tokens.ADD_MENU, items)
            elif self._keymap_manager is not None:
                self._keymap_manager.add_set(toon.game)
        elif kind == L.HOME:
            self.toggle_home_panel(wid)

    # -- home block: quick menu and compact launcher -----------------------------

    def toggle_home_panel(self, wid: str) -> HomePanel | None:
        if self._popovers.open_tag(wid) == "home":
            self._popovers.close(wid)
            return None
        surface = self._follower.surface(wid)
        if surface is None:
            return None
        panel = HomePanel(surface.strip.style_name(), surface.strip.scale(),
                          running=self._session.is_running(),
                          accounts=read_accounts(self._launcher),
                          can_launch=self._launcher is not None)
        panel.row_chosen.connect(lambda key, wid=wid: self._home_row(wid, key))
        panel.launch_requested.connect(self._launch_account)
        panel.full_launcher_requested.connect(
            lambda wid=wid: self._leave_for(wid, WINDOW_LAUNCHER))
        panel.view_changed.connect(lambda _view, wid=wid: self._popovers.refit(wid))
        if self._popovers.open_card(wid, "home", L.HOME, 0, panel, align=LEFT) is None:
            return None
        return panel

    def _leave_for(self, wid: str, target: str) -> None:
        self._popovers.close(wid)
        self.open_window_requested.emit(target)

    def _home_row(self, wid: str, key: str) -> None:
        if key == home_mod.SETTINGS:
            self._leave_for(wid, WINDOW_SETTINGS)
        elif key == home_mod.OPEN_WINDOW:
            self._leave_for(wid, WINDOW_MAIN)
        elif key == home_mod.TOGGLE_RUNNING:
            self._popovers.close(wid)
            self._toggle_running()
        elif key == home_mod.QUIT:
            self._popovers.close(wid)
            self.quit_requested.emit()

    def _toggle_running(self) -> None:
        toggle = getattr(self._session, "toggle_running", None)
        if callable(toggle):
            toggle()
        elif self._session.is_running():
            self._session.stop()
        else:
            self._session.start()

    def _launch_account(self, account_id: str) -> None:
        if self._launcher is None:
            return
        try:
            self._launcher.launch(account_id)
        except Exception as exc:
            print(f"[Strips] launch of account {account_id} failed: {exc}")
        self._refresh_home_panel()

    def _home_panel(self) -> HomePanel | None:
        if self._home_wid is None or self._popovers.open_tag(self._home_wid) != "home":
            return None
        panel = self._popovers.open_content(self._home_wid)
        return panel if isinstance(panel, HomePanel) else None

    def _refresh_home_panel(self) -> None:
        """Accounts or the service changed while the panel is open."""
        panel = self._home_panel()
        if panel is None:
            return
        before = panel.sizeHint()
        panel.set_running(self._session.is_running())
        panel.set_accounts(read_accounts(self._launcher))
        if panel.sizeHint() != before:
            self._popovers.refit(self._home_wid)

    def _popover_opened(self, wid: str, tag: str) -> None:
        if tag == "home":
            self.set_home_open(True)

    def _popover_closed(self, wid: str, tag: str) -> None:
        if tag == "home":
            self.set_home_open(False)

    # -- menus ----------------------------------------------------------------

    def _on_context(self, wid: str, kind: str, number: int) -> None:
        toon = self._session.toon(wid)
        if toon is None:
            return
        if kind == L.KEYSET:
            last_visible = len(self._keysets.visible_numbers(toon.game)) < 2
            items = [
                MenuItem("edit", "Edit keyset",
                         disabled=self._keymap_manager is None),
                MenuItem("hide", "Hide keyset",
                         disabled=last_visible or self._keymap_manager is None),
            ]
            self._popovers.toggle_menu(wid, f"set:{number}", L.KEYSET, number,
                                       tokens.set_color(number), items)
        elif kind in (L.PORTRAIT, L.NAME):
            running = self._session.is_running()
            items = [
                MenuItem("lock", "Lock counters", checked=bool(toon.counters_locked)),
                MenuItem("color", "Change color\u2026", disabled=not toon.name),
                MenuItem("stop", "Stop all toons" if running else "Start all toons"),
                MenuItem("open", "Open MultiTool"),
            ]
            self._popovers.toggle_menu(wid, "toon", IDENTITY, 0, toon.accent, items)

    def _on_menu(self, wid: str, tag: str, key: str) -> None:
        toon = self._session.toon(wid)
        if toon is None:
            return
        km = self._keymap_manager
        if tag == "toon":
            if key == "lock":
                self._toggle_lock(wid)
            elif key == "color":
                if toon.name:
                    self.appearance_requested.emit(toon.game, toon.name)
            elif key == "stop":
                self._toggle_running()
            elif key == "open":
                self.open_window_requested.emit(WINDOW_MAIN)
        elif tag.startswith("set:"):
            number = int(tag.split(":", 1)[1])
            if key == "edit":
                self.open_editor(wid, number)
            elif key == "hide" and km is not None:
                set_id = self._keysets.id_for(toon.game, number)
                if set_id is not None:
                    km.set_hidden(toon.game, set_id, True)
        elif tag == "add" and km is not None:
            if key == "new":
                km.add_set(toon.game)
            elif key.startswith("show:"):
                set_id = self._keysets.id_for(toon.game, int(key.split(":", 1)[1]))
                if set_id is not None:
                    km.set_hidden(toon.game, set_id, False)

    # -- keyset editor ----------------------------------------------------------

    def _editor_kind(self) -> str:
        raw = None
        if self._settings is not None:
            try:
                raw = self._settings.get(settings_keys.KEYSET_EDITOR_LAYOUT)
            except Exception:
                raw = None
        return settings_keys.normalize_keyset_editor_layout(raw)

    def open_editor(self, wid: str, number: int) -> KeysetEditor | None:
        """The editor card for keyset `number`, under its button on this strip."""
        toon = self._session.toon(wid)
        surface = self._follower.surface(wid)
        km = self._keymap_manager
        if toon is None or surface is None or km is None:
            return None
        model = build_editor_model(km, toon.game, number)
        if model is None:
            return None
        card = KeysetEditor(model, self._editor_kind(), surface.strip.style_name(),
                            surface.strip.scale())
        game = toon.game
        card.bind_requested.connect(
            lambda action, key, game=game, number=number:
            km.update_set_key(game, number - 1, action, key))
        card.layout_changed.connect(lambda kind, wid=wid: self._editor_kind_changed(wid, kind))
        card.close_requested.connect(lambda wid=wid: self._popovers.close(wid))
        # While the card waits for a key, Escape belongs to the capture.
        card.capture_changed.connect(self._popovers.watch.pause_escape)
        if self._popovers.open_card(wid, f"edit:{number}", L.KEYSET, number, card) is None:
            return None
        return card

    def _editor_kind_changed(self, wid: str, kind: str) -> None:
        if self._settings is not None:
            try:
                self._settings.set(settings_keys.KEYSET_EDITOR_LAYOUT, kind)
            except Exception:
                pass
        self._popovers.refit(wid)

    def _refresh_editors(self) -> None:
        """A binding changed, or the set was hidden, moved or deleted."""
        for wid in list(self._follower.surfaces()):
            tag = self._popovers.open_tag(wid)
            if not tag.startswith("edit:"):
                continue
            card = self._popovers.open_content(wid)
            toon = self._session.toon(wid)
            number = int(tag.split(":", 1)[1])
            model = (build_editor_model(self._keymap_manager, toon.game, number)
                     if toon is not None else None)
            visible = toon is not None and number in self._keysets.visible_numbers(toon.game)
            if model is None or not visible or not isinstance(card, KeysetEditor):
                self._popovers.close(wid)
                continue
            before = card.sizeHint()
            card.set_model(model)
            if card.sizeHint() != before:
                self._popovers.refit(wid)
