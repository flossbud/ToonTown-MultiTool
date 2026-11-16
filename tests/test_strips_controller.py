"""The controller: one strip per toon from a ToonSession."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from services.toon_session import GAME_TTR, ToonState
from services.toon_session_fake import DEMO_KEYSET_IDS, FakeToonSession
from utils import settings_keys
from utils.overlay.backend import OverlayBackend
from utils.strips import layout as L
from utils.strips.attach import AttachStrategy
from utils.strips.controller import KeysetView, StripController, build_model
from utils.strips.follow import StripFollower

WIDS = ["101", "102", "103", "104"]


class Backend(OverlayBackend):
    def apply_input_region(self, window, region):
        self.last = QRegion(region)


class Strategy(AttachStrategy):
    name = "test"
    logical_native = True


class Keymaps:
    """The slice of KeymapManager a strip reads and writes."""

    def __init__(self, ttr=3, cc=2):
        self.sets = {
            "ttr": [{"id": f"t{i:07x}", "name": f"Set {i + 1}"} for i in range(ttr)],
            "cc": [{"id": f"c{i:07x}", "name": f"Set {i + 1}"} for i in range(cc)],
        }
        self.listeners = []

    def get_sets(self, game):
        return [dict(s) for s in self.sets.get(game, [])]

    def on_change(self, cb):
        self.listeners.append(cb)

    def notify(self):
        for cb in self.listeners:
            cb()

    def add_set(self, game):
        n = len(self.sets[game])
        if n >= 8:
            return None
        self.sets[game].append({"id": f"{game[0]}{n:07x}", "name": f"Set {n + 1}"})
        self.notify()
        return self.sets[game][-1]["id"]

    def hide(self, game, index, hidden=True):
        self.sets[game][index]["hidden"] = hidden
        self.notify()

    def set_hidden(self, game, set_id, hidden):
        for entry in self.sets[game]:
            if entry["id"] == set_id:
                entry["hidden"] = bool(hidden)
                self.notify()
                return True
        return False


class Settings:
    def __init__(self, **values):
        self.values = dict(values)
        self.callbacks = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        for cb in self.callbacks:
            cb(key, value)

    def on_change(self, cb):
        self.callbacks.append(cb)


def settle():
    for _ in range(4):
        QApplication.processEvents()


@pytest.fixture
def rig(qapp):
    made = []

    def _rig(session=None, keymaps=None, settings=None, today=None, widths=None):
        session = session or FakeToonSession.demo(window_ids=WIDS)
        rects = {wid: (100 + 900 * i, 50, (widths or {}).get(wid, 800), 600)
                 for i, wid in enumerate(WIDS)}
        follower = StripFollower(Strategy(), Backend(), geometry_fn=rects.get,
                                 scale=1.0)
        controller = StripController(
            session, follower, keymap_manager=keymaps, settings_manager=settings,
            keyset_ids=None if keymaps is not None else DEMO_KEYSET_IDS,
            today_fn=(lambda: today) if today is not None else None)
        controller.start()
        follower.tracker.stop()          # tests sample by hand
        follower.tracker.sample_now()
        follower.tracker.sample_now()
        settle()
        made.append(controller)
        return session, controller, rects

    yield _rig
    for c in made:
        c.shutdown()
    settle()


def model(controller, wid):
    return controller.follower.surface(wid).strip.model()


def click(controller, wid, kind, number=0):
    strip = controller.follower.surface(wid).strip
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier,
                     strip.block_rect(kind, number).center().toPoint())
    settle()


# -- one strip per toon ---------------------------------------------------------

def test_one_presented_strip_per_toon(rig):
    session, controller, _rects = rig()
    surfaces = controller.follower.surfaces()
    assert sorted(surfaces) == WIDS
    assert all(s.is_presented() for s in surfaces.values())
    assert [model(controller, w).name for w in WIDS] == [
        "Flossbud", "Hector", "Moe", "Linux"]
    assert model(controller, "101").accent == "#4a8fe7"
    assert model(controller, "103").game == "cc"
    assert model(controller, "103").species == "cat"


def test_home_block_is_on_toon_one_only(rig):
    _session, controller, _rects = rig()
    assert [model(controller, w).home for w in WIDS] == [True, False, False, False]
    assert controller.home_window() == "101"


def test_home_block_moves_on_when_toon_ones_window_closes(rig):
    session, controller, _rects = rig()
    moved = []
    controller.home_moved.connect(moved.append)
    before = controller.follower.surface("102").width()
    session.remove_toon("101")
    settle()
    assert controller.follower.surface("101") is None
    assert sorted(controller.follower.surfaces()) == ["102", "103", "104"]
    assert moved == ["102"]
    assert [model(controller, w).home for w in WIDS[1:]] == [True, False, False]
    # The strip grew by the home block and is still centred on its window.
    surface = controller.follower.surface("102")
    assert surface.width() == before + 28 + 3 + 6
    assert abs(surface.geometry().x() + surface.width() / 2 - (1000 + 400)) <= 1


def test_home_block_follows_the_lowest_slot_not_arrival_order(rig):
    session, controller, _rects = rig()
    session.update_toon("101", slot=9)        # re-slotted behind everyone
    settle()
    assert controller.home_window() == "102"
    assert not model(controller, "101").home


def test_a_new_window_gets_a_strip(rig):
    session, controller, rects = rig()
    session.remove_toon("104")
    settle()
    rects["105"] = (100, 700, 800, 600)
    session.add_toon(ToonState(
        window_id="105", slot=3, game=GAME_TTR, name=None, species=None,
        dna=None, accent="#4a8fe7", enabled=True, keep_alive=False,
        click_sync=False, click_sync_supported=True, keyset_id="demo-ttr-1",
        counters_locked=False, beans=None, bank=None, tokens=None, laff=None,
        max_laff=None))
    settle()
    assert "105" in controller.follower.surfaces()
    assert model(controller, "105").name == "Toon 4"     # until the API names it
    session.update_toon("105", name="Daisy", species="duck")
    settle()
    assert model(controller, "105").name == "Daisy"


# -- which blocks a strip has ---------------------------------------------------

def test_click_sync_block_is_omitted_where_it_cannot_run(rig):
    """Corporate Clash has no click sync: the block is absent, not unlit."""
    _session, controller, _rects = rig()
    moe = controller.follower.surface("103").strip
    assert model(controller, "103").click_sync is None
    assert moe.block_rect(L.CLICK_SYNC) is None
    assert moe.block_rect(L.KEEP_ALIVE) is not None
    hector = controller.follower.surface("102").strip
    assert model(controller, "102").click_sync is False       # supported, off
    assert hector.block_rect(L.CLICK_SYNC) is not None


def test_features_off_app_wide_omit_their_blocks_and_keep_the_toons_flags(rig):
    session, controller, _rects = rig()
    session.set_features(keep_alive_available=False)
    settle()
    assert all(model(controller, w).keep_alive is None for w in WIDS)
    assert controller.follower.surface("101").strip.block_rect(L.KEEP_ALIVE) is None
    assert session.toon("101").keep_alive is True              # kept underneath
    session.set_features(keep_alive_available=True, click_sync_available=False)
    settle()
    assert model(controller, "101").keep_alive is True
    assert all(model(controller, w).click_sync is None for w in WIDS)
    session.set_features(click_sync_available=True)
    settle()
    assert model(controller, "101").click_sync is True
    assert model(controller, "103").click_sync is None         # still unsupported


def test_all_strips_dim_when_the_service_is_stopped(rig):
    session, controller, _rects = rig()
    assert [model(controller, w).dimmed for w in WIDS] == [False, False, False, True]
    session.stop()
    settle()
    assert all(model(controller, w).dimmed for w in WIDS)
    # Each toon keeps its own enabled flag: Enable stays lit on the first three.
    assert [model(controller, w).enabled for w in WIDS] == [True, True, True, False]
    session.start()
    settle()
    assert [model(controller, w).dimmed for w in WIDS] == [False, False, False, True]


def test_click_sync_state_reaches_the_strip(rig):
    session, controller, _rects = rig()
    strip = controller.follower.surface("101").strip
    block = strip.strip_layout().find(L.CLICK_SYNC)
    assert model(controller, "101").click_sync_state == "armed"   # alone in the group
    assert "second toon" in strip.tooltip_for(block)
    session.set_click_sync("102", True)
    settle()
    assert model(controller, "101").click_sync_state == "active"
    assert strip.tooltip_for(block) == "Click Sync"
    session.set_click_sync_error("no pointer access")
    settle()
    assert model(controller, "101").click_sync_state == "error"
    assert strip.tooltip_for(block) == "Click Sync: no pointer access"
    session.set_click_sync_error(None)
    settle()
    assert model(controller, "101").click_sync_error == ""


# -- clicks go to the session ---------------------------------------------------

def test_toggles_go_through_the_session(rig):
    session, controller, _rects = rig()
    click(controller, "101", L.ENABLE)
    assert session.toon("101").enabled is False
    assert model(controller, "101").enabled is False
    click(controller, "102", L.KEEP_ALIVE)
    assert session.toon("102").keep_alive is False
    click(controller, "102", L.CLICK_SYNC)
    assert session.toon("102").click_sync is True
    assert model(controller, "102").click_sync is True


def test_keyset_click_selects_by_id(rig):
    session, controller, _rects = rig()
    assert model(controller, "101").active == 1
    assert model(controller, "102").active == 2
    click(controller, "101", L.KEYSET, 3)
    assert session.toon("101").keyset_id == controller.keysets.id_for("ttr", 3)
    assert model(controller, "101").active == 3
    assert model(controller, "102").active == 2          # other toons untouched


def test_only_the_changed_strip_is_rebuilt(rig):
    session, controller, _rects = rig()
    untouched = model(controller, "102")
    session.set_enabled("101", False)
    settle()
    assert model(controller, "102") is untouched


# -- keysets come from the keymap manager -----------------------------------------

def _session_with_ids(keymaps):
    """The demo toons, all on the first real set of their game."""
    ids = {g: [sets[0]["id"]] for g, sets in keymaps.sets.items()}
    return FakeToonSession.demo(window_ids=WIDS, keyset_ids=ids)


def test_buttons_are_the_visible_sets_numbered_by_position(rig):
    keymaps = Keymaps(ttr=4, cc=2)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    assert model(controller, "101").keysets == (1, 2, 3, 4)
    assert model(controller, "103").keysets == (1, 2)          # per game
    keymaps.hide("ttr", 1)
    settle()
    m = model(controller, "101")
    assert m.keysets == (1, 3, 4)            # hidden sets keep their numbers
    assert m.hidden_sets and m.show_add
    assert not model(controller, "103").hidden_sets


def test_click_maps_the_number_back_to_the_real_id(rig):
    keymaps = Keymaps(ttr=4)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    keymaps.hide("ttr", 1)
    settle()
    click(controller, "101", L.KEYSET, 3)
    assert session.toon("101").keyset_id == "t0000002"
    assert model(controller, "101").active == 3


def test_add_appends_a_set_and_goes_away_at_the_maximum(rig):
    keymaps = Keymaps(ttr=7)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    assert model(controller, "101").show_add
    click(controller, "101", L.ADD)
    assert len(keymaps.sets["ttr"]) == 8
    m = model(controller, "101")
    assert m.keysets == tuple(range(1, 9)) and not m.show_add
    assert controller.follower.surface("101").strip.block_rect(L.ADD) is None
    # Every TTR strip gained the button; the Clash strip did not.
    assert model(controller, "102").keysets == tuple(range(1, 9))
    assert model(controller, "103").keysets == (1, 2)


def test_add_with_hidden_sets_opens_the_restore_menu(rig):
    keymaps = Keymaps(ttr=4)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    keymaps.hide("ttr", 2)
    keymaps.hide("ttr", 3)
    settle()
    click(controller, "101", L.ADD)
    assert len(keymaps.sets["ttr"]) == 4                 # nothing added yet
    assert controller.popovers.open_tag("101") == "add"
    menu = controller.popovers.open_content("101")
    assert [(i.label, i.disabled) for i in menu.items()] == [
        ("Show keyset 3", False), ("Show keyset 4", False), ("New keyset", False)]
    menu.chosen.emit("show:4")
    settle()
    assert controller.popovers.open_tag("101") == ""
    assert model(controller, "101").keysets == (1, 2, 4)
    click(controller, "101", L.ADD)
    controller.popovers.open_content("101").chosen.emit("new")
    settle()
    assert len(keymaps.sets["ttr"]) == 5


def test_new_keyset_is_disabled_at_the_maximum(rig):
    keymaps = Keymaps(ttr=8)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    keymaps.hide("ttr", 7)
    settle()
    click(controller, "101", L.ADD)
    items = controller.popovers.open_content("101").items()
    assert [(i.label, i.disabled) for i in items] == [
        ("Show keyset 8", False), ("New keyset", True)]


def test_keyset_view_maps_ids_and_numbers():
    view = KeysetView(None, DEMO_KEYSET_IDS)
    assert view.visible_numbers("ttr") == (1, 2, 3)
    assert view.number_for("ttr", "demo-ttr-2") == 2
    assert view.id_for("ttr", 2) == "demo-ttr-2"
    assert not view.can_add("ttr")            # nothing to add a set to
    assert KeysetView(None).visible_numbers("ttr") == ()
    keymaps = Keymaps(ttr=3)
    view = KeysetView(keymaps)
    assert view.number_for("ttr", "t0000002") == 3
    assert view.number_for("ttr", "zzzz") == 0       # unknown: nothing lit
    assert view.number_for("cc", "t0000002") == 0    # ids are per game
    assert view.id_for("ttr", 9) is None
    assert view.can_add("ttr")
    keymaps.sets["ttr"] = keymaps.sets["ttr"] * 3    # nine entries: full
    assert not view.can_add("ttr")


# -- look, menus, pure model ----------------------------------------------------

def test_look_comes_from_settings_and_follows_changes(rig):
    settings = Settings(**{settings_keys.FLOAT_STRIP_STYLE: "flat"})
    _session, controller, _rects = rig(settings=settings)
    strip = controller.follower.surface("101").strip
    assert strip.style_name() == "flat"
    settings.set(settings_keys.FLOAT_STRIP_STYLE, "neon")
    settle()
    assert strip.style_name() == "neon"
    settings.set("something_else", "flat")
    settle()
    assert strip.style_name() == "neon"


def right_click(controller, wid, kind, number=0):
    strip = controller.follower.surface(wid).strip
    QTest.mouseClick(strip, Qt.RightButton, Qt.NoModifier,
                     strip.block_rect(kind, number).center().toPoint())
    settle()


def test_keyset_right_click_menu(rig):
    keymaps = Keymaps(ttr=2)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    right_click(controller, "102", L.KEYSET, 2)
    assert controller.popovers.open_tag("102") == "set:2"
    menu = controller.popovers.open_content("102")
    assert [(i.label, i.disabled) for i in menu.items()] == [
        ("Edit keyset", False), ("Hide keyset", False)]
    # A second right-click on the same button closes it.
    right_click(controller, "102", L.KEYSET, 2)
    assert controller.popovers.open_tag("102") == ""
    right_click(controller, "102", L.KEYSET, 2)
    menu = controller.popovers.open_content("102")
    QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier,
                     menu.pill_rect(1).center().toPoint())
    settle()
    assert keymaps.sets["ttr"][1].get("hidden") is True
    assert model(controller, "102").keysets == (1,)
    # One visible set left: it cannot be hidden.
    right_click(controller, "102", L.KEYSET, 1)
    menu = controller.popovers.open_content("102")
    assert [i.disabled for i in menu.items()] == [False, True]
    assert [i.label for i in menu.items()] == ["Edit keyset", "Hide keyset"]


def test_one_popover_per_strip_and_strips_are_independent(rig):
    _session, controller, _rects = rig()
    right_click(controller, "101", L.KEYSET, 1)
    right_click(controller, "101", L.KEYSET, 2)
    assert controller.popovers.open_tag("101") == "set:2"
    right_click(controller, "102", L.PORTRAIT)
    assert controller.popovers.open_tag("101") == "set:2"
    assert controller.popovers.open_tag("102") == "toon"


def test_toon_menu(rig):
    session, controller, _rects = rig()
    looks, windows = [], []
    controller.appearance_requested.connect(lambda g, n: looks.append((g, n)))
    controller.open_window_requested.connect(windows.append)

    def choose(key):
        right_click(controller, "102", L.NAME)
        assert controller.popovers.open_tag("102") == "toon"
        menu = controller.popovers.open_content("102")
        menu.chosen.emit(key)
        settle()
        return menu

    menu = choose("lock")
    assert [i.label for i in menu.items()] == [
        "Lock counters", "Change color\u2026", "Stop all toons", "Open MultiTool"]
    assert not menu.items()[0].checked
    assert session.toon("102").counters_locked is True
    assert choose("color").items()[0].checked          # the lock shows its check now
    assert looks == [("ttr", "Hector")]
    choose("stop")
    assert session.is_running() is False
    assert choose("open").items()[2].label == "Start all toons"
    assert windows == ["main"]
    choose("stop")
    assert session.is_running() is True


# -- counters -----------------------------------------------------------------

def test_locked_counters_show_without_hover_and_follow_the_lock(rig):
    session, controller, _rects = rig()
    pops = controller.popovers
    assert pops.counters_shown("101")            # Flossbud's are locked in the demo
    assert not pops.counters_shown("102")
    session.set_counters_locked("101", False)
    settle()
    assert not pops.counters_shown("101")


def test_counters_show_on_hover_and_linger_to_reach_the_lock(rig, qapp):
    session, controller, _rects = rig()
    pops = controller.popovers
    pops.set_identity_hover("102", True)
    settle()
    assert pops.counters_shown("102")
    view = pops._entries["102"].counters_view
    assert (view.model().beans, view.model().bank) == (87, 9200)
    # The pointer leaves the name and reaches the counters within the linger.
    pops.set_identity_hover("102", False)
    pops._counters_hover("102", True)
    QTest.qWait(250)
    assert pops.counters_shown("102")
    # The lock is pressed: the session hears it and the counters stay.
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                     view.lock_rect().center().toPoint())
    settle()
    assert session.toon("102").counters_locked is True
    pops._counters_hover("102", False)
    QTest.qWait(250)
    assert pops.counters_shown("102")
    # Unlocked and not hovered: gone after the linger.
    session.set_counters_locked("102", False)
    QTest.qWait(250)
    assert not pops.counters_shown("102")


def test_counters_sit_centred_under_portrait_and_name(rig):
    _session, controller, _rects = rig()
    pops = controller.popovers
    surface = controller.follower.surface("101")
    identity = pops.anchor_rect("101", "identity")
    counters = pops._entries["101"].counters_surface.geometry()
    assert abs(counters.center().x() - identity.center().x()) <= 1
    assert counters.top() == identity.top() + identity.height()   # no gap to cross
    assert surface.geometry().contains(identity)


def test_token_cell_only_for_ttr_during_cartoonival(rig):
    import datetime
    _session, controller, _rects = rig(today=datetime.date(2026, 10, 1))
    assert controller.counters_for("101").tokens == 310
    assert controller.counters_for("103").tokens is None       # Corporate Clash
    assert controller.counters_for("104").tokens == 0           # zero is a value


def test_no_token_cell_outside_cartoonival(rig):
    import datetime
    _session, controller, _rects = rig(today=datetime.date(2026, 11, 16))
    assert controller.counters_for("101").tokens is None
    assert controller.counters_for("101").beans == 456


def test_collapsed_strip_puts_the_name_in_the_counters(rig):
    _session, controller, _rects = rig(widths={"102": 320})
    assert controller.follower.surface("102").strip.strip_layout().collapse == L.NO_NAME
    assert controller.counters_for("102").name == "Hector"
    assert controller.counters_for("101").name == ""


def test_moving_window_takes_counters_and_menus_with_it(rig):
    _session, controller, rects = rig()
    pops = controller.popovers
    right_click(controller, "101", L.KEYSET, 2)
    assert pops.open_tag("101") == "set:2" and pops.counters_shown("101")
    rects["101"] = (160, 50, 800, 600)
    controller.follower.tracker.sample_now()          # moving: strip concealed
    settle()
    assert pops.open_tag("101") == "" and not pops.counters_shown("101")
    controller.follower.tracker.sample_now()          # at rest again
    settle()
    assert pops.counters_shown("101")                 # locked counters return
    assert pops.open_tag("101") == ""                 # a menu does not
    identity = pops.anchor_rect("101", "identity")
    assert abs(pops._entries["101"].counters_surface.geometry().center().x()
               - identity.center().x()) <= 1


def test_closing_a_window_drops_what_hung_off_its_strip(rig):
    session, controller, _rects = rig()
    right_click(controller, "101", L.KEYSET, 2)
    session.remove_toon("101")
    settle()
    assert "101" not in controller.popovers._entries
    assert not controller.popovers.watch.is_watching()


# -- keyset editor (on the real KeymapManager) -----------------------------------

@pytest.fixture
def real_keymaps(tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "cfg"))
    from utils.keymap_manager import KeymapManager
    km = KeymapManager()
    for game in ("ttr", "cc"):
        while len(km.get_set_ids(game)) < 3:
            km.add_set(game)
    return km


def _real_session(km):
    return FakeToonSession.demo(
        window_ids=WIDS, keyset_ids={g: km.get_set_ids(g) for g in ("ttr", "cc")})


def open_editor(controller, wid, number):
    right_click(controller, wid, L.KEYSET, number)
    controller.popovers.open_content(wid).chosen.emit("edit")
    settle()
    return controller.popovers.open_content(wid)


def test_edit_keyset_opens_the_card_under_its_button(rig, real_keymaps):
    from utils.strips.popovers.editor import KeysetEditor
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    card = open_editor(controller, "101", 2)
    assert isinstance(card, KeysetEditor)
    assert controller.popovers.open_tag("101") == "edit:2"
    assert card.model().number == 2
    # Rows come from the game's own actions: TTR has Action and no Sprint.
    actions = [a for a, _label in card.model().actions]
    assert "action" in actions and "sprint" not in actions
    assert card.model().key_of("forward") == real_keymaps.get_set("ttr", 1)["forward"]
    # Dropped under keyset 2's button.
    anchor = controller.popovers.anchor_rect("101", L.KEYSET, 2)
    geo = controller.popovers.open_surface("101").geometry()
    assert geo.top() >= anchor.top() + anchor.height()
    assert abs(geo.center().x() - anchor.center().x()) <= 1


def test_clash_editor_has_sprint(rig, real_keymaps):
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    card = open_editor(controller, "103", 1)
    actions = [a for a, _label in card.model().actions]
    assert "sprint" in actions and "action" not in actions


def test_pressing_a_key_rebinds_through_the_keymap_manager(rig, real_keymaps, qapp):
    from PySide6.QtWidgets import QWidget
    from utils import chord_capture_state
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    card = open_editor(controller, "101", 2)
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("cap", "gags").center().toPoint())
    assert card.listening() == "gags"
    assert QWidget.keyboardGrabber() is card
    assert chord_capture_state.is_active()
    QTest.keyClick(card, Qt.Key_K)
    settle()
    assert real_keymaps.get_set("ttr", 1)["gags"] == "k"
    assert real_keymaps.get_set("ttr", 0)["gags"] != "k"       # only that set
    # The keyboard went back the moment the key arrived.
    assert card.listening() == "" and QWidget.keyboardGrabber() is None
    assert not chord_capture_state.is_active()
    # The open card shows the new binding.
    assert controller.popovers.open_content("101").model().key_of("gags") == "k"


def test_escape_cancels_the_capture_and_keeps_the_binding(rig, real_keymaps):
    from PySide6.QtWidgets import QWidget
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    before = real_keymaps.get_set("ttr", 1)["gags"]
    card = open_editor(controller, "101", 2)
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("cap", "gags").center().toPoint())
    QTest.keyClick(card, Qt.Key_Escape)
    settle()
    assert real_keymaps.get_set("ttr", 1)["gags"] == before
    assert QWidget.keyboardGrabber() is None
    assert controller.popovers.open_tag("101") == "edit:2"     # the card stays


def test_closing_the_card_mid_capture_gives_the_keyboard_back(rig, real_keymaps):
    from PySide6.QtWidgets import QWidget
    from utils import chord_capture_state
    session, controller, rects = rig(_real_session(real_keymaps), real_keymaps)
    for how in ("close", "move", "window-gone"):
        card = open_editor(controller, "102", 1)
        QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                         card.zone_rect("cap", "jump").center().toPoint())
        assert QWidget.keyboardGrabber() is card
        if how == "close":
            controller.popovers.close_all()            # a click elsewhere
        elif how == "move":
            x, y, w, h = rects["102"]
            rects["102"] = (x + 40, y, w, h)
            controller.follower.tracker.sample_now()
        else:
            session.remove_toon("102")
        settle()
        assert QWidget.keyboardGrabber() is None, how
        assert not chord_capture_state.is_active(), how
        if how == "move":
            controller.follower.tracker.sample_now()
            settle()


def test_escape_belongs_to_the_capture_while_it_runs(rig, real_keymaps):
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    watch = controller.popovers.watch
    card = open_editor(controller, "101", 2)
    assert not watch._paused
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("cap", "gags").center().toPoint())
    assert watch._paused
    QTest.keyClick(card, Qt.Key_Escape)
    assert not watch._paused


def test_keys_layout_binds_by_clicking_and_is_remembered(rig, real_keymaps):
    settings = Settings()
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps, settings)
    card = open_editor(controller, "101", 2)
    assert card.kind() == "list"
    height = controller.popovers.open_surface("101").height()
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("kind", "keys").center().toPoint())
    settle()
    assert settings.get(settings_keys.KEYSET_EDITOR_LAYOUT) == "keys"
    assert controller.popovers.open_surface("101").height() > height
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("chip", "tasks").center().toPoint())
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("key", "p").center().toPoint())
    settle()
    assert real_keymaps.get_set("ttr", 1)["tasks"] == "p"
    # The next editor opens in the layout last used.
    controller.popovers.close_all()
    assert open_editor(controller, "102", 1).kind() == "keys"


def test_conflicts_are_marked_and_explained(rig, real_keymaps):
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    card = open_editor(controller, "101", 2)
    assert card.model().conflicts == frozenset() 
    forward = real_keymaps.get_set("ttr", 1)["forward"]
    real_keymaps.update_set_key("ttr", 1, "jump", forward)
    settle()
    model = controller.popovers.open_content("101").model()
    assert model.conflicts == frozenset({"forward", "jump"})
    assert "Forward and Jump" in model.note
    # A key that means something else in another set is explained, not marked.
    real_keymaps.update_set_key("ttr", 1, "jump", "space")
    real_keymaps.update_set_key("ttr", 1, "gags", "x")
    real_keymaps.update_set_key("ttr", 0, "tasks", "x")
    settle()
    model = controller.popovers.open_content("101").model()
    assert model.conflicts == frozenset()
    assert model.note == "X is Tasks in keyset 1"


def test_hiding_the_edited_set_closes_its_card(rig, real_keymaps):
    session, controller, _rects = rig(_real_session(real_keymaps), real_keymaps)
    open_editor(controller, "101", 3)
    real_keymaps.set_hidden("ttr", real_keymaps.id_at("ttr", 2), True)
    settle()
    assert controller.popovers.open_tag("101") == ""


def test_edit_is_disabled_without_a_keymap_manager(rig):
    _session, controller, _rects = rig()
    right_click(controller, "101", L.KEYSET, 1)
    items = controller.popovers.open_content("101").items()
    assert [i.disabled for i in items] == [True, True]


def test_home_click_is_reported(rig):
    _session, controller, _rects = rig()
    homes = []
    controller.home_clicked.connect(homes.append)
    click(controller, "101", L.HOME)
    assert homes == ["101"]
    controller.set_home_open(True)
    assert model(controller, "101").home_open
    assert not model(controller, "102").home_open


def test_build_model_is_pure():
    toon = FakeToonSession.demo().toons()[2]             # Moe, Corporate Clash
    kwargs = dict(home=False, running=True, keep_alive_available=True,
                  click_sync_available=True,
                  keysets=KeysetView(None, DEMO_KEYSET_IDS))
    assert build_model(toon, **kwargs) == build_model(toon, **kwargs)
    m = build_model(toon, **kwargs)
    assert (m.name, m.game, m.keep_alive, m.click_sync, m.active) == (
        "Moe", "cc", False, None, 2)
    assert build_model(toon, **{**kwargs, "running": False}).dimmed
