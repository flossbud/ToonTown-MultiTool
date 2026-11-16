"""ToonSession: the per-window model, its signals, and what it tells the
routing layer. Everything the session talks to is a stand-in (see
tests/toon_session_harness.py)."""

import threading
import time
from types import SimpleNamespace

import pytest

from services.toon_session import ToonSession, ToonState
from tests.toon_session_harness import (
    KEEP_ALIVE_ON, FakeKeymaps, FakeProfiles, Rig, profile,
)
from utils.settings_keys import CLICK_SYNC_ENABLED


@pytest.fixture
def make(qapp, tmp_path):
    rigs = []

    def _make(**kwargs):
        rig = Rig(tmp_path, **kwargs)
        rigs.append(rig)
        return rig

    yield _make
    for rig in rigs:
        rig.close()


def pump(qapp, until, timeout=3.0):
    """Run the event loop until ``until()`` is true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return False


# ── Construction ───────────────────────────────────────────────────────────

def test_starts_empty_and_running(make):
    rig = make()
    assert rig.session.toons() == []
    assert rig.session.toon("nope") is None
    assert rig.session.is_running()
    assert rig.session.active_profile == -1


def test_not_activated_starts_nothing(make):
    rig = make()
    assert rig.input.calls == []
    assert rig.wm.calls == []


def test_activate_starts_the_services_and_stamps_once(make, capsys):
    rig = make(activate=True)
    rig.session.activate()
    assert capsys.readouterr().out.count("[ToonSession] core active") == 1
    assert rig.input.calls == ["start"]
    assert rig.wm.calls == ["enable_detection"]


def test_input_service_gets_the_session_as_its_source(make):
    rig = make()
    kwargs = rig.input.kwargs
    assert kwargs["window_manager"] is rig.wm
    assert kwargs["settings_manager"] is rig.settings
    assert kwargs["keymap_manager"] is rig.keymaps
    assert kwargs["get_event_queue_func"]() is rig.session.key_event_queue
    assert kwargs["get_enabled_toons"]() == [False] * 4
    assert rig.input._last_known_foreground_game == "ttr"


def test_windows_present_at_construction_are_picked_up(make):
    rig = make(windows=["a", "b"], games={"b": "cc"})
    assert [(t.window_id, t.slot, t.game) for t in rig.session.toons()] == [
        ("a", 0, "ttr"), ("b", 1, "cc")]


def test_handles(make):
    rig = make()
    session = rig.session
    assert session.input_service is rig.input
    assert session.customizations is rig.customizations
    assert session.click_sync_service is rig.click_sync
    assert session.ghost_cursor_controller is None
    assert session.key_event_queue.maxsize == 200
    for name in ("input_service", "key_event_queue", "customizations",
                 "click_sync_service", "ghost_cursor_controller"):
        with pytest.raises(AttributeError):
            setattr(session, name, object())


def test_input_log_reaches_the_logger(make):
    rig = make()
    rig.input.input_log.emit("[Input] hello")
    assert "[Input] hello" in rig.logs


# ── The toon table ─────────────────────────────────────────────────────────

def test_a_new_window_becomes_a_toon(make):
    rig = make()
    rig.wm.set_windows(["a"])
    assert rig.spy.events == [("toons",)]
    assert rig.session.toons() == [ToonState(
        window_id="a", slot=0, game="ttr", name=None, species=None, dna=None,
        accent="#4a8fe7", enabled=True, keep_alive=False, click_sync=False,
        click_sync_supported=True, keyset_id="0", counters_locked=False,
        beans=None, bank=None, tokens=None, laff=None, max_laff=None)]


def test_corporate_clash_window(make):
    rig = make()
    rig.wm.set_windows(["c"], games={"c": "cc"})
    toon = rig.session.toon("c")
    assert (toon.game, toon.accent, toon.click_sync_supported) == ("cc", "#f26d21", False)


def test_no_click_sync_on_this_platform_means_unsupported_everywhere(make):
    rig = make(click_sync=False)
    rig.wm.set_windows(["a"])
    assert rig.session.click_sync_service is None
    assert rig.session.toon("a").click_sync_supported is False
    assert rig.session.click_sync_available() is False


def test_the_same_window_list_again_announces_nothing(make):
    rig = make()
    rig.wm.set_windows(["a", "b"])
    rig.spy.events.clear()
    rig.wm.set_windows(["a", "b"])
    assert rig.spy.events == []


def test_only_four_windows_become_toons(make):
    rig = make()
    rig.wm.set_windows(["a", "b", "c", "d", "e"])
    assert [t.window_id for t in rig.session.toons()] == ["a", "b", "c", "d"]


def test_a_closed_window_takes_its_toon_with_it(make):
    rig = make()
    rig.wm.set_windows(["a", "b"])
    rig.spy.events.clear()
    rig.wm.set_windows(["b"])
    assert rig.spy.events == [("toons",)]
    assert [(t.window_id, t.slot) for t in rig.session.toons()] == [("b", 0)]
    assert rig.session.toon("a") is None


def test_state_follows_the_window_not_the_slot(make):
    """What the old tab did by copying four parallel lists around."""
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.set_enabled("a", False)
    rig.session.set_keep_alive("b", True)
    rig.session.set_keyset("c", "2")
    rig.ttr("c", "Linux", beans=250)
    rig.spy.events.clear()

    rig.wm.set_windows(["c", "a", "b"])       # same windows, new order

    assert rig.spy.events == [("toons",)]
    by_id = {t.window_id: t for t in rig.session.toons()}
    assert [t.window_id for t in rig.session.toons()] == ["c", "a", "b"]
    assert (by_id["a"].slot, by_id["a"].enabled) == (1, False)
    assert (by_id["b"].slot, by_id["b"].keep_alive) == (2, True)
    assert (by_id["c"].slot, by_id["c"].keyset_id, by_id["c"].name,
            by_id["c"].beans) == (0, "2", "Linux", 250)
    # ...and the routing layer reads the same thing by slot.
    assert rig.session._get_enabled_toons() == [True, False, True, False]
    assert rig.session._get_keymap_assignments() == [2, 0, 0, 0]
    assert rig.session._slot_keep_alive == [False, False, True, False]


def test_only_a_new_window_starts_enabled(make):
    """The tab re-enabled every disabled toon whenever the list changed."""
    rig = make()
    rig.wm.set_windows(["a"])
    rig.session.set_enabled("a", False)
    rig.wm.set_windows(["a", "b"])
    assert rig.session.toon("a").enabled is False
    assert rig.session.toon("b").enabled is True
    rig.wm.set_windows(["a"])
    assert rig.session.toon("a").enabled is False


def test_a_game_resolved_late_is_announced(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.spy.events.clear()
    rig.wm.set_windows(["a"], games={"a": "cc"})
    assert rig.spy.events == [("toon", "a")]
    assert rig.session.toon("a").game == "cc"


def test_window_manager_signals_from_another_thread_land_on_the_gui_thread(make, qapp):
    rig = make()
    seen = []
    rig.session.toons_changed.connect(lambda: seen.append(threading.get_ident()))
    worker = threading.Thread(target=lambda: rig.wm.set_windows(["a"]))
    worker.start()
    worker.join()
    assert seen == []                       # not delivered on the poll thread
    assert pump(qapp, lambda: bool(seen))
    assert seen == [threading.get_ident()]
    assert rig.session.toon("a") is not None


# ── Setters ────────────────────────────────────────────────────────────────

@pytest.fixture
def two(make):
    rig = make(settings={**KEEP_ALIVE_ON, CLICK_SYNC_ENABLED: True})
    rig.wm.set_windows(["a", "b"])
    rig.spy.events.clear()
    return rig


@pytest.mark.parametrize("setter, field, value", [
    ("set_enabled", "enabled", False),
    ("set_keep_alive", "keep_alive", True),
    ("set_click_sync", "click_sync", True),
    ("set_keyset", "keyset_id", "1"),
    ("set_counters_locked", "counters_locked", True),
])
def test_setter_changes_one_field_and_emits_once(two, setter, field, value):
    before = two.session.toon("a")
    other = two.session.toon("b")
    getattr(two.session, setter)("a", value)
    after = two.session.toon("a")
    assert getattr(after, field) == value
    assert after == ToonState(**{**before.__dict__, field: value})
    assert two.session.toon("b") == other
    assert two.spy.events == [("toon", "a")]


@pytest.mark.parametrize("setter, value", [
    ("set_enabled", True), ("set_keep_alive", False), ("set_click_sync", False),
    ("set_keyset", "0"), ("set_counters_locked", False),
])
def test_setter_with_the_current_value_emits_nothing(two, setter, value):
    getattr(two.session, setter)("a", value)
    assert two.spy.events == []


@pytest.mark.parametrize("setter, value", [
    ("set_enabled", False), ("set_keep_alive", True), ("set_click_sync", True),
    ("set_keyset", "1"), ("set_counters_locked", True),
])
def test_setter_on_an_unknown_window_is_ignored(two, setter, value):
    getattr(two.session, setter)("gone", value)
    assert two.spy.events == []


def test_setters_run_on_the_callers_thread_which_is_the_gui_thread(two):
    seen = []
    two.session.toon_changed.connect(lambda wid: seen.append(threading.get_ident()))
    two.session.set_enabled("a", False)
    assert seen == [threading.get_ident()]


def test_enabled_reaches_the_routing_layer_by_slot(two):
    two.session.set_enabled("b", False)
    assert two.session._get_enabled_toons() == [True, False, False, False]
    assert "[Input] Toon 2 (slot 2): input disabled" in two.logs


# ── Stop and start ─────────────────────────────────────────────────────────

def test_stop_turns_broadcast_off_and_keeps_every_flag(two):
    two.session.set_enabled("b", False)
    two.session.set_keep_alive("a", True)
    before = two.session.toons()
    two.spy.events.clear()

    two.session.stop()

    assert two.spy.events == [("running", False)]
    assert not two.session.is_running()
    assert two.session.toons() == before             # nothing vanished or changed
    assert two.session._get_enabled_toons() == [False] * 4
    two.session.stop()
    assert two.spy.events == [("running", False)]


def test_stop_leaves_the_router_thread_and_detection_alone(make):
    """Stopped is the tab's Idle state (service on, nobody enabled), not its
    Stop: the old Stop also dropped the window list."""
    rig = make(activate=True, windows=["a"])
    rig.session.stop()
    assert rig.input.calls == ["start"]
    assert rig.wm.calls == ["enable_detection"]
    assert rig.session.toon("a") is not None


def test_start_restores_what_stop_hid(two):
    two.session.set_enabled("b", False)
    two.session.stop()
    two.spy.events.clear()
    two.session.start()
    assert two.spy.events == [("running", True)]
    assert two.session._get_enabled_toons() == [True, False, False, False]
    two.session.start()
    assert two.spy.events == [("running", True)]


def test_toggle_running(two):
    two.session.toggle_running()
    two.session.toggle_running()
    assert two.spy.events == [("running", False), ("running", True)]


def test_a_window_that_opens_while_stopped_is_enabled_but_silent(two):
    two.session.stop()
    two.wm.set_windows(["a", "b", "c"])
    assert two.session.toon("c").enabled is True
    assert two.session._get_enabled_toons() == [False] * 4
    two.session.start()
    assert two.session._get_enabled_toons() == [True, True, True, False]


# ── Chat ───────────────────────────────────────────────────────────────────

def test_chat_mode_normalizes_legacy_values(make):
    rig = make(settings={"chat_handling_mode": "advanced"})
    assert rig.session._get_chat_handling_mode() == "per_toon"
    rig.settings.data["chat_handling_mode"] = "simple"
    assert rig.session._get_chat_handling_mode() == "focused_only"


def test_chat_mode_defaults_without_settings(qapp, tmp_path):
    from tests.toon_session_harness import (
        FakeCustomizations, FakeInhibitor, FakeWindowManager, StubInputService)
    from services.toon_prefs import ToonPrefs
    session = ToonSession(
        FakeWindowManager(), customizations=FakeCustomizations(),
        prefs=ToonPrefs(str(tmp_path / "p.json")), sleep_inhibitor=FakeInhibitor(),
        input_service_factory=StubInputService,
        click_sync_builder=lambda s: None, activate=False)
    try:
        assert session._get_chat_handling_mode() == "focused_only"
        assert session.keep_alive_available() is False
        assert session.click_sync_available() is False
    finally:
        session.shutdown()


@pytest.mark.parametrize("mode, expected", [
    ("focused_only", [False, False, False, False]),
    ("all_toons", [True, False, True, False]),
    ("keyset_dynamic", [True, False, False, False]),   # enabled AND on set 0
    ("per_toon", [True, False, True, True]),           # raw flags; empty slot = True
])
def test_effective_chat_by_mode(make, mode, expected):
    rig = make(settings={"chat_handling_mode": mode})
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.set_enabled("b", False)
    rig.session.set_keyset("c", "1")
    assert rig.session._get_chat_enabled() == expected


def test_no_toon_chats_while_stopped(make):
    rig = make(settings={"chat_handling_mode": "all_toons"})
    rig.wm.set_windows(["a", "b"])
    rig.session.stop()
    assert rig.session._get_chat_enabled() == [False] * 4


# ── Keysets ────────────────────────────────────────────────────────────────

def test_set_keyset_rejects_an_id_the_keymaps_do_not_have(two):
    two.session.set_keyset("a", "7")
    assert two.session.toon("a").keyset_id == "0"
    assert two.spy.events == []


def test_keyset_ids_are_per_game(make):
    rig = make()
    rig.wm.set_windows(["t", "c"], games={"c": "cc"})
    rig.session.set_keyset("t", "2")          # ttr has three sets
    rig.session.set_keyset("c", "2")          # cc has two
    assert rig.session.toon("t").keyset_id == "2"
    assert rig.session.toon("c").keyset_id == "0"


def test_a_sets_own_id_wins_over_its_position(make):
    keymaps = FakeKeymaps(ttr=[{"name": "Default", "id": "base"},
                               {"name": "Arrows", "id": "k-arrows"}])
    rig = make(keymaps=keymaps)
    rig.wm.set_windows(["a"])
    assert rig.session.toon("a").keyset_id == "base"
    rig.session.set_keyset("a", "1")                     # a position is not an id
    assert rig.session.toon("a").keyset_id == "base"
    rig.session.set_keyset("a", "k-arrows")
    assert rig.session.toon("a").keyset_id == "k-arrows"
    assert rig.session._get_keymap_assignments() == [1, 0, 0, 0]
    keymaps.sets["ttr"].reverse()                        # reordered: ids hold
    keymaps.changed()
    assert rig.session.toon("a").keyset_id == "k-arrows"
    assert rig.session._get_keymap_assignments() == [0, 0, 0, 0]


def test_deleting_a_toons_keyset_moves_it_to_the_lowest_visible(two):
    two.session.set_keyset("a", "2")
    two.spy.events.clear()
    two.keymaps.sets["ttr"].pop()             # set "2" is gone
    two.keymaps.changed()
    assert two.session.toon("a").keyset_id == "0"
    assert two.spy.events == [("toon", "a")]
    assert two.session._get_keymap_assignments() == [0, 0, 0, 0]


def test_hiding_a_toons_keyset_moves_it_to_the_lowest_visible(two):
    two.session.set_keyset("a", "1")
    two.session.set_keyset("b", "2")
    two.spy.events.clear()
    two.keymaps.sets["ttr"][0]["hidden"] = True
    two.keymaps.sets["ttr"][1]["hidden"] = True
    two.keymaps.changed()
    assert two.session.toon("a").keyset_id == "2"     # lowest that is visible
    assert two.session.toon("b").keyset_id == "2"
    assert two.spy.events == [("toon", "a")]


def test_a_new_toon_starts_on_the_lowest_visible_keyset(make):
    keymaps = FakeKeymaps(ttr=[{"name": "Default", "hidden": True}, {"name": "Arrows"}])
    rig = make(keymaps=keymaps)
    rig.wm.set_windows(["a"])
    assert rig.session.toon("a").keyset_id == "1"


def test_an_unrelated_keymap_edit_announces_nothing(two):
    two.keymaps.changed()
    assert two.spy.events == []


def test_keymap_callbacks_from_another_thread_are_marshalled(two, qapp):
    two.session.set_keyset("a", "2")
    two.spy.events.clear()
    seen = []
    two.session.toon_changed.connect(lambda wid: seen.append(threading.get_ident()))
    two.keymaps.sets["ttr"].pop()
    worker = threading.Thread(target=two.keymaps.changed)
    worker.start()
    worker.join()
    assert seen == []
    assert pump(qapp, lambda: bool(seen))
    assert seen == [threading.get_ident()]


def test_settings_callbacks_from_another_thread_are_marshalled(two, qapp):
    seen = []
    two.session.features_changed.connect(lambda: seen.append(threading.get_ident()))
    worker = threading.Thread(
        target=lambda: two.settings.set("keep_alive_enabled", False))
    worker.start()
    worker.join()
    assert seen == []
    assert pump(qapp, lambda: bool(seen))
    assert seen == [threading.get_ident()]


# ── Remembered per toon ────────────────────────────────────────────────────

def test_choices_are_remembered_per_toon_identity(make, tmp_path):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud")
    rig.session.set_keyset("a", "2")
    rig.session.set_counters_locked("a", True)
    from services.toon_prefs import ToonPrefs
    assert ToonPrefs(rig.prefs_path).get("ttr::Flossbud") == {
        "keyset_id": "2", "counters_locked": True}


def test_remembered_choices_come_back_when_the_toon_is_named(make):
    rig = make()
    rig.prefs.update("ttr::Flossbud", keyset_id="1", counters_locked=True)
    rig.wm.set_windows(["w9"])
    assert rig.session.toon("w9").keyset_id == "0"
    rig.spy.events.clear()
    rig.ttr("w9", "Flossbud")
    toon = rig.session.toon("w9")
    assert (toon.keyset_id, toon.counters_locked) == ("1", True)
    assert rig.spy.events == [("toon", "w9")]
    assert rig.session._get_keymap_assignments() == [1, 0, 0, 0]


def test_identity_is_per_game(make):
    rig = make()
    rig.prefs.update("cc::Moe", keyset_id="1")
    rig.wm.set_windows(["t"])
    rig.ttr("t", "Moe")
    assert rig.session.toon("t").keyset_id == "0"


def test_a_choice_made_before_the_name_arrives_wins_and_is_remembered(make):
    rig = make()
    rig.prefs.update("ttr::Flossbud", keyset_id="1", counters_locked=True)
    rig.wm.set_windows(["a"])
    rig.session.set_keyset("a", "2")
    rig.ttr("a", "Flossbud")
    toon = rig.session.toon("a")
    assert (toon.keyset_id, toon.counters_locked) == ("2", True)
    assert rig.prefs.get("ttr::Flossbud")["keyset_id"] == "2"


def test_a_remembered_keyset_that_no_longer_exists_is_not_applied(make):
    rig = make()
    rig.prefs.update("ttr::Flossbud", keyset_id="9")
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud")
    assert rig.session.toon("a").keyset_id == "0"


def test_a_name_dropping_out_and_returning_changes_nothing(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud")
    rig.session.set_keyset("a", "1")
    rig.session.set_counters_locked("a", True)
    rig.ttr("a", None)
    toon = rig.session.toon("a")
    assert (toon.name, toon.keyset_id, toon.counters_locked) == (None, "1", True)
    rig.ttr("a", "Flossbud")
    toon = rig.session.toon("a")
    assert (toon.name, toon.keyset_id, toon.counters_locked) == ("Flossbud", "1", True)


def test_a_different_toon_in_the_same_window_gets_its_own_choices(make):
    rig = make()
    rig.prefs.update("ttr::Hector", keyset_id="2")
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud")
    rig.session.set_keyset("a", "1")
    rig.session.set_counters_locked("a", True)
    rig.ttr("a", "Hector")
    toon = rig.session.toon("a")
    assert (toon.name, toon.keyset_id, toon.counters_locked) == ("Hector", "2", False)
    assert rig.prefs.get("ttr::Flossbud") == {"keyset_id": "1", "counters_locked": True}
    rig.ttr("a", "Linux")                   # nothing remembered: defaults
    toon = rig.session.toon("a")
    assert (toon.keyset_id, toon.counters_locked) == ("0", False)


# ── Game data ──────────────────────────────────────────────────────────────

RABBIT_DNA = "7410" + "00" * 13       # head byte 0x10: a rabbit


def test_ttr_data_fills_the_toon_and_emits_once(make):
    rig = make()
    rig.wm.set_windows(["a", "b"])
    rig.spy.events.clear()
    rig.ttr("a", "Flossbud", dna="zz", color="#4A8FE7", laff=120, max_laff=137,
            beans=456, bank=12840, tokens=310)
    toon = rig.session.toon("a")
    assert (toon.name, toon.dna, toon.accent) == ("Flossbud", "zz", "#4a8fe7")
    assert (toon.laff, toon.max_laff, toon.beans, toon.bank, toon.tokens) == (
        120, 137, 456, 12840, 310)
    assert toon.identity == "ttr::Flossbud"
    assert rig.spy.events == [("toon", "a")]
    rig.ttr("a", "Flossbud", dna="zz", color="#4A8FE7", laff=120, max_laff=137,
            beans=456, bank=12840, tokens=310)
    assert rig.spy.events == [("toon", "a")]          # same data: silent


def test_species_comes_from_the_dna(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud", dna=RABBIT_DNA)
    assert rig.session.toon("a").species == "rabbit"
    rig.ttr("a", "Flossbud", dna="not-hex")
    assert rig.session.toon("a").species is None


def test_tokens_keep_none_apart_from_zero(make):
    rig = make()
    rig.wm.set_windows(["a", "b"])
    rig.ttr("a", "Linux", tokens=0)
    rig.ttr("b", "Hector", tokens=None)
    assert rig.session.toon("a").tokens == 0
    assert rig.session.toon("b").tokens is None


def test_data_from_a_superseded_fetch_is_dropped(make):
    rig = make()
    rig.wm.set_windows(["a"])
    result = (["Old"], [""], [None], [None], [None], [None], [None], [None])
    rig.session._refresh_gen += 1
    rig.session._apply_ttr_data((rig.session._refresh_gen - 1, ["a"], result))
    assert rig.session.toon("a").name is None


def test_data_for_a_window_that_closed_is_ignored(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.spy.events.clear()
    rig.ttr("gone", "Ghost")
    assert rig.spy.events == []


def test_cc_data(make):
    rig = make()
    rig.wm.set_windows(["c"], games={"c": "cc"})
    rig.spy.events.clear()
    info = SimpleNamespace(name="Moe", species_name="Cat",
                           dna_colors=((0.906, 0.537, 0.290),) * 5)
    rig.cc("c", info)
    toon = rig.session.toon("c")
    assert (toon.name, toon.species, toon.accent, toon.dna) == (
        "Moe", "cat", "#e7894a", None)
    assert (toon.beans, toon.bank, toon.laff) == (None, None, None)
    assert rig.spy.events == [("toon", "c")]
    rig.cc("c", None)                         # logged out
    assert rig.session.toon("c").name is None
    assert rig.session.toon("c").accent == "#f26d21"


def test_accent_prefers_the_users_colour_then_the_games_then_the_brand(make):
    rig = make()
    rig.wm.set_windows(["a"])
    assert rig.session.toon("a").accent == "#4a8fe7"         # brand
    rig.ttr("a", "Flossbud", color="#abc")
    assert rig.session.toon("a").accent == "#aabbcc"         # reported by the game
    rig.customizations.entries[("ttr", "Flossbud")] = {"accent": "#E74A4A"}
    rig.spy.events.clear()
    rig.session.customization_changed("ttr", "Flossbud")
    assert rig.session.toon("a").accent == "#e74a4a"         # the user's
    assert rig.spy.events == [("toon", "a")]
    rig.customizations.entries[("ttr", "Flossbud")] = {"accent": "not a colour"}
    rig.session.customization_changed()
    assert rig.session.toon("a").accent == "#aabbcc"


def test_resolved_toons_reach_the_launcher(make, monkeypatch):
    from utils.game_registry import GameRegistry
    monkeypatch.setattr(GameRegistry, "pid_for_window", staticmethod(lambda wid: 4242))
    discovered = []
    monkeypatch.setattr(
        "utils.toon_renders.ToonRenders.instance",
        classmethod(lambda cls: SimpleNamespace(
            discovered=lambda game, name, dna: discovered.append((game, name, dna)))))
    rig = make()
    captured = []
    rig.session.set_toon_capture_sink(
        lambda pid, name, dna, **meta: captured.append((pid, name, dna, meta)))
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Flossbud", dna="d1", color="#4a8fe7", laff=100, max_laff=137)
    rig.ttr("a", "Flossbud", dna="d1", color="#4a8fe7", laff=100, max_laff=137)
    assert discovered == [("ttr", "Flossbud", "d1")]         # once per (name, dna)
    assert len(captured) == 1                                 # unchanged: skipped
    pid, name, dna, meta = captured[0]
    assert (pid, name, dna) == (4242, "Flossbud", "d1")
    assert (meta["laff"], meta["max_laff"], meta["accent"]) == (100, 137, "#4a8fe7")
    rig.ttr("a", "Flossbud", dna="d1", color="#4a8fe7", laff=90, max_laff=137)
    assert len(captured) == 2                                 # laff moved


def test_fetch_runs_off_the_gui_thread_and_applies_on_it(make, monkeypatch, qapp):
    import services.toon_session as mod
    fetch_threads = []

    def fake_fetch(count, wids):
        fetch_threads.append(threading.get_ident())
        return (["Flossbud"], [""], ["#4a8fe7"], [1], [2], [3], [4], [None])

    monkeypatch.setattr(mod, "get_toon_names_by_slot", fake_fetch)
    rig = make(windows=["a"])
    applied = []
    rig.session.toon_changed.connect(lambda wid: applied.append(threading.get_ident()))
    rig.session._fetch_toon_data()
    assert pump(qapp, lambda: bool(applied))
    assert fetch_threads and fetch_threads[0] != threading.get_ident()
    assert applied == [threading.get_ident()]
    assert rig.session.toon("a").name == "Flossbud"
    assert rig.session._fetch_inflight == set()


def test_no_fetch_when_the_companion_apis_are_switched_off(make, monkeypatch):
    import services.toon_session as mod
    monkeypatch.setattr(mod, "get_toon_names_by_slot",
                        lambda *a: (_ for _ in ()).throw(AssertionError("fetched")))
    rig = make(windows=["a"], settings={"enable_companion_app": False,
                                        "enable_cc_companion_app": False})
    rig.session._fetch_toon_data()
    assert rig.session._fetch_inflight == set()


# ── Refresh ────────────────────────────────────────────────────────────────

def _bare():
    # The cooldown helper reads one attribute; skip the constructor.
    session = ToonSession.__new__(ToonSession)
    session._last_refresh_monotonic = float("-inf")
    return session


def test_first_refresh_is_accepted_even_at_a_low_clock():
    assert _bare()._refresh_is_coalesced(0.1) is False


def test_second_refresh_inside_the_window_is_coalesced():
    session = _bare()
    assert session._refresh_is_coalesced(100.0) is False
    assert session._refresh_is_coalesced(100.0 + ToonSession.REFRESH_COOLDOWN_S - 0.1) is True


def test_refresh_after_the_window_is_accepted_and_moves_it():
    session = _bare()
    assert session._refresh_is_coalesced(100.0) is False
    assert session._refresh_is_coalesced(102.0) is False
    assert session._refresh_is_coalesced(102.5) is True


def test_a_coalesced_refresh_does_no_work(make, monkeypatch):
    import services.toon_session as mod
    rig = make(windows=["a"])
    monkeypatch.setattr(rig.session, "_refresh_is_coalesced", lambda now: True)
    monkeypatch.setattr(mod, "invalidate_port_to_wid_cache",
                        lambda: (_ for _ in ()).throw(AssertionError("heavy path ran")))
    rig.session.refresh()
    assert any("coalesced" in m for m in rig.logs)
    assert rig.input.calls == [] and rig.wm.calls == []


def test_refresh_restarts_the_router_and_redetects(make):
    rig = make(windows=["a"])
    rig.session.key_event_queue.put(("keydown", "w"))
    rig.spy.events.clear()
    rig.session.refresh()
    assert rig.input.calls == ["stop", "start"]
    assert rig.wm.calls == ["clear_window_ids"]
    assert rig.session.key_event_queue.empty()
    assert rig.session.toons() == [] and rig.spy.events == [("toons",)]
    rig.session.refresh()                       # mashed: inside the cooldown
    assert rig.input.calls == ["stop", "start"]


def test_refresh_works_the_same_while_stopped(make):
    rig = make(windows=["a"])
    rig.session.stop()
    rig.session.refresh()
    assert rig.input.calls == ["stop", "start"]
    assert rig.wm.calls == ["clear_window_ids"]
    assert not rig.session.is_running()


def test_a_keyset_chosen_this_session_survives_a_refresh(make):
    rig = make(windows=["a", "b"])
    rig.session.set_keyset("a", "2")
    rig.session.set_counters_locked("a", True)
    rig.session.refresh()
    rig.wm.set_windows(["a", "b"])              # re-detected
    a, b = rig.session.toon("a"), rig.session.toon("b")
    assert (a.keyset_id, a.counters_locked) == ("2", True)
    assert (b.keyset_id, b.counters_locked) == ("0", False)


# ── Profiles ───────────────────────────────────────────────────────────────

def test_load_profile_applies_to_live_toons_by_slot(make):
    profiles = FakeProfiles({1: profile(
        [True, False, True, True], modes=["Arrows", "Default", "Third", "Default"],
        keep_alive=[True, False, False, False])})
    rig = make(settings=KEEP_ALIVE_ON, profiles=profiles)
    rig.wm.set_windows(["a", "b"])
    rig.spy.events.clear()

    rig.session.load_profile(1)

    a, b = rig.session.toon("a"), rig.session.toon("b")
    assert (a.enabled, a.keyset_id, a.keep_alive) == (True, "1", True)
    assert (b.enabled, b.keyset_id, b.keep_alive) == (False, "0", False)
    assert rig.spy.events == [("toon", "a"), ("toon", "b")]
    assert rig.session.active_profile == 1
    assert any("Loaded 'Profile 2'" in m for m in rig.logs)
    assert rig.session._keep_alive_running is True


def test_load_profile_without_a_manager_is_a_no_op(make):
    rig = make()
    rig.session._profile_manager = None
    rig.session.load_profile(0)
    assert rig.session.active_profile == -1


def test_a_profile_set_name_the_game_does_not_have_leaves_the_keyset(make):
    profiles = FakeProfiles({0: profile([True] * 4, modes=["Nope"] * 4)})
    rig = make(profiles=profiles)
    rig.wm.set_windows(["a"])
    rig.session.set_keyset("a", "1")
    rig.session.load_profile(0)
    assert rig.session.toon("a").keyset_id == "1"


def test_the_active_profile_is_saved_when_a_toon_or_keyset_changes(make):
    profiles = FakeProfiles({0: profile([True] * 4)})
    rig = make(settings=KEEP_ALIVE_ON, profiles=profiles)
    rig.wm.set_windows(["a", "b"])
    rig.session.set_enabled("a", False)
    assert profiles.saved == []                     # no profile active yet
    rig.session.load_profile(0)
    rig.session.set_keep_alive("b", True)           # not a save point, as before
    assert profiles.saved == []
    rig.session.set_enabled("a", False)
    assert profiles.saved[-1] == (
        0, [False, True, False, False], ["Default"] * 4,
        [False, True, False, False], [False] * 4)
    rig.session.set_keyset("b", "1")
    assert profiles.saved[-1][2] == ["Default", "Arrows", "Default", "Default"]


def test_switching_profiles_saves_the_one_left_behind(make):
    profiles = FakeProfiles({0: profile([True] * 4), 1: profile([False] * 4)})
    rig = make(profiles=profiles)
    rig.wm.set_windows(["a"])
    rig.session.load_profile(0)
    rig.session.load_profile(1)
    assert [s[0] for s in profiles.saved] == [0]
    assert rig.session.toon("a").enabled is False


# ── Shutdown ───────────────────────────────────────────────────────────────

def test_shutdown_stops_everything_once(make):
    rig = make(settings=KEEP_ALIVE_ON, activate=True, windows=["a"])
    rig.session.set_keep_alive("a", True)
    rig.session.shutdown()
    rig.session.shutdown()
    assert rig.input.calls == ["start", "shutdown"]
    assert rig.click_sync.calls.count(("shutdown",)) == 1
    assert rig.session._keep_alive_running is False
    assert not rig.session._poll_timer.isActive()
    assert rig.inhibitor.calls[-1] == "release"


def test_nothing_is_announced_after_shutdown(make):
    rig = make(windows=["a"])
    rig.session.shutdown()
    rig.spy.events.clear()
    rig.wm.set_windows(["a", "b"])
    rig.keymaps.changed()
    rig.settings.set("keep_alive_enabled", True)
    rig.session.start()
    assert rig.spy.events == []
