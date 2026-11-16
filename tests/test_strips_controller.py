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

    def _rig(session=None, keymaps=None, settings=None):
        session = session or FakeToonSession.demo(window_ids=WIDS)
        rects = {wid: (100 + 900 * i, 50, 800, 600) for i, wid in enumerate(WIDS)}
        follower = StripFollower(Strategy(), Backend(), geometry_fn=rects.get,
                                 scale=1.0)
        controller = StripController(
            session, follower, keymap_manager=keymaps, settings_manager=settings,
            keyset_ids=None if keymaps is not None else DEMO_KEYSET_IDS)
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


def test_add_with_hidden_sets_asks_for_the_menu_instead(rig):
    keymaps = Keymaps(ttr=3)
    session, controller, _rects = rig(_session_with_ids(keymaps), keymaps)
    keymaps.hide("ttr", 2)
    settle()
    asked = []
    controller.add_menu_requested.connect(asked.append)
    click(controller, "101", L.ADD)
    assert asked == ["101"] and len(keymaps.sets["ttr"]) == 3


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


def test_right_click_and_home_are_reported_with_the_window(rig):
    _session, controller, _rects = rig()
    menus, homes = [], []
    controller.context_requested.connect(lambda w, k, n: menus.append((w, k, n)))
    controller.home_clicked.connect(homes.append)
    strip = controller.follower.surface("102").strip
    QTest.mouseClick(strip, Qt.RightButton, Qt.NoModifier,
                     strip.block_rect(L.KEYSET, 2).center().toPoint())
    click(controller, "101", L.HOME)
    assert menus == [("102", L.KEYSET, 2)]
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
