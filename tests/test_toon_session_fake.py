"""FakeToonSession: same surface as ToonSession, and the signal contract."""

import dataclasses
import inspect

import pytest

from services.toon_session import ToonSession, ToonState, toon_identity
from services.toon_session_fake import FakeToonSession


class Spy:
    """Records every emission of the four session signals, in order."""

    def __init__(self, session):
        self.events = []
        session.toons_changed.connect(lambda: self.events.append(("toons",)))
        session.toon_changed.connect(lambda wid: self.events.append(("toon", wid)))
        session.running_changed.connect(lambda on: self.events.append(("running", on)))
        session.features_changed.connect(lambda: self.events.append(("features",)))


@pytest.fixture
def demo(qapp):
    return FakeToonSession.demo()


@pytest.fixture
def spy(demo):
    return Spy(demo)


def _public(cls):
    # Constants (tunables of the real engine) are not part of the surface.
    return {name for name in vars(cls)
            if not name.startswith("_") and not name.isupper()}


# ── Surface ────────────────────────────────────────────────────────────────

def test_fake_has_every_public_member_of_the_real_session():
    missing = _public(ToonSession) - _public(FakeToonSession)
    assert not missing, f"FakeToonSession lacks: {sorted(missing)}"


def test_fake_methods_take_the_same_arguments():
    for name in sorted(_public(ToonSession)):
        real = getattr(ToonSession, name)
        if not inspect.isfunction(real):
            continue
        fake = getattr(FakeToonSession, name)
        assert (list(inspect.signature(fake).parameters)
                == list(inspect.signature(real).parameters)), name


def test_fake_properties_are_read_only(demo):
    for name in ("input_service", "key_event_queue", "customizations",
                 "click_sync_service", "ghost_cursor_controller"):
        assert isinstance(getattr(ToonSession, name), property)
        assert isinstance(getattr(FakeToonSession, name), property)
        with pytest.raises(AttributeError):
            setattr(demo, name, object())


def test_toon_state_is_immutable(demo):
    state = demo.toons()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.enabled = False


def test_toon_identity_key():
    assert toon_identity("ttr", "Flossbud") == "ttr::Flossbud"
    assert toon_identity("cc", None) is None
    assert toon_identity("cc", "") is None


# ── Demo data ──────────────────────────────────────────────────────────────

def test_demo_matches_the_handoff(demo):
    toons = demo.toons()
    assert [(t.name, t.game) for t in toons] == [
        ("Flossbud", "ttr"), ("Hector", "ttr"), ("Moe", "cc"), ("Linux", "ttr")]
    assert [t.slot for t in toons] == [0, 1, 2, 3]
    assert [t.accent for t in toons] == ["#4a8fe7", "#e74a4a", "#e7894a", "#56c856"]
    assert [t.identity for t in toons] == [
        "ttr::Flossbud", "ttr::Hector", "cc::Moe", "ttr::Linux"]
    flossbud, hector, moe, linux = toons
    assert (flossbud.beans, flossbud.bank, flossbud.tokens) == (456, 12840, 310)
    assert moe.tokens is None            # no Cartoonival on Corporate Clash
    assert linux.tokens == 0             # a real zero, not "no value"
    assert [t.counters_locked for t in toons] == [True, False, False, False]
    # Mixed toggles, so every pill state shows up in a render.
    assert {t.enabled for t in toons} == {True, False}
    assert {t.keep_alive for t in toons} == {True, False}
    assert {t.click_sync for t in toons} == {True, False}
    # Click sync exists for Toontown Rewritten windows only.
    assert [t.click_sync_supported for t in toons] == [True, True, False, True]
    assert moe.click_sync is False
    assert [t.keyset_id for t in toons] == [
        "demo-ttr-1", "demo-ttr-2", "demo-cc-2", "demo-ttr-1"]
    assert demo.is_running()
    assert demo.keep_alive_available() and demo.click_sync_available()


def test_demo_accepts_real_window_ids(qapp):
    session = FakeToonSession.demo(window_ids=[101, 102, 103, 104])
    assert [t.window_id for t in session.toons()] == ["101", "102", "103", "104"]
    assert session.toon("103").name == "Moe"
    with pytest.raises(ValueError):
        FakeToonSession.demo(window_ids=["only-one"])


def test_demo_sits_on_the_keysets_the_harness_has(qapp):
    session = FakeToonSession.demo(keyset_ids={"ttr": ["aa", "bb"], "cc": ["cc"]})
    # Corporate Clash has a single set here, so Moe falls back to it.
    assert [t.keyset_id for t in session.toons()] == ["aa", "bb", "cc", "aa"]


def test_toon_lookup(demo):
    assert demo.toon("demo-2").name == "Hector"
    assert demo.toon("nope") is None


def test_handles(demo):
    assert demo.input_service is None
    assert demo.key_event_queue.empty()
    sink = lambda *a, **k: None  # noqa: E731
    demo.set_toon_capture_sink(sink)
    assert demo._toon_capture_sink is sink


# ── Setters ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("setter, field, wid, value", [
    ("set_enabled", "enabled", "demo-1", False),
    ("set_enabled", "enabled", "demo-4", True),
    ("set_keep_alive", "keep_alive", "demo-3", True),
    ("set_keep_alive", "keep_alive", "demo-1", False),
    ("set_click_sync", "click_sync", "demo-2", True),
    ("set_click_sync", "click_sync", "demo-1", False),
    ("set_keyset", "keyset_id", "demo-1", "demo-ttr-3"),
    ("set_counters_locked", "counters_locked", "demo-2", True),
    ("set_counters_locked", "counters_locked", "demo-1", False),
])
def test_setter_changes_the_field_and_emits_once(demo, spy, setter, field, wid, value):
    before = demo.toon(wid)
    getattr(demo, setter)(wid, value)
    after = demo.toon(wid)
    assert getattr(after, field) == value
    assert dataclasses.replace(after, **{field: getattr(before, field)}) == before
    assert spy.events == [("toon", wid)]


@pytest.mark.parametrize("setter, wid, value", [
    ("set_enabled", "demo-1", True),
    ("set_keep_alive", "demo-1", True),
    ("set_click_sync", "demo-1", True),
    ("set_keyset", "demo-1", "demo-ttr-1"),
    ("set_counters_locked", "demo-1", True),
])
def test_setter_with_the_current_value_emits_nothing(demo, spy, setter, wid, value):
    getattr(demo, setter)(wid, value)
    assert spy.events == []


@pytest.mark.parametrize("setter, value", [
    ("set_enabled", True), ("set_keep_alive", True), ("set_click_sync", True),
    ("set_keyset", "1"), ("set_counters_locked", True),
])
def test_setter_on_an_unknown_window_is_ignored(demo, spy, setter, value):
    getattr(demo, setter)("gone", value)
    assert spy.events == []
    assert len(demo.toons()) == 4


def test_setter_leaves_other_toons_alone(demo):
    others = [t for t in demo.toons() if t.window_id != "demo-1"]
    demo.set_enabled("demo-1", False)
    assert [t for t in demo.toons() if t.window_id != "demo-1"] == others


# ── Feature gates ──────────────────────────────────────────────────────────

def test_feature_flags_emit_only_on_change(demo, spy):
    demo.set_features(keep_alive_available=True, click_sync_available=True)
    assert spy.events == []
    demo.set_features(keep_alive_available=False)
    assert spy.events == [("features",)]
    assert not demo.keep_alive_available() and demo.click_sync_available()
    demo.set_features(keep_alive_available=True, click_sync_available=False)
    assert spy.events == [("features",), ("features",)]


def test_keep_alive_cannot_be_turned_on_while_unavailable(demo, spy):
    demo.set_features(keep_alive_available=False)
    spy.events.clear()
    demo.set_keep_alive("demo-3", True)
    assert demo.toon("demo-3").keep_alive is False
    assert spy.events == []


def test_keep_alive_can_be_turned_off_while_unavailable(demo, spy):
    demo.set_features(keep_alive_available=False)
    spy.events.clear()
    demo.set_keep_alive("demo-1", False)
    assert demo.toon("demo-1").keep_alive is False
    assert spy.events == [("toon", "demo-1")]


def test_click_sync_cannot_be_turned_on_while_unavailable(demo, spy):
    demo.set_features(click_sync_available=False)
    spy.events.clear()
    demo.set_click_sync("demo-2", True)
    assert demo.toon("demo-2").click_sync is False
    assert spy.events == []


def test_click_sync_cannot_be_turned_on_where_unsupported(demo, spy):
    assert demo.toon("demo-3").click_sync_supported is False
    demo.set_click_sync("demo-3", True)
    assert demo.toon("demo-3").click_sync is False
    assert spy.events == []


def test_click_sync_can_be_turned_off_where_unsupported(demo, spy):
    demo.update_toon("demo-3", click_sync=True)      # however it got there
    spy.events.clear()
    demo.set_click_sync("demo-3", False)
    assert demo.toon("demo-3").click_sync is False
    assert spy.events == [("toon", "demo-3")]


def test_feature_going_away_keeps_each_toons_choice(demo):
    demo.set_features(keep_alive_available=False, click_sync_available=False)
    assert demo.toon("demo-1").keep_alive is True
    assert demo.toon("demo-1").click_sync is True


# ── Running ────────────────────────────────────────────────────────────────

def test_start_and_stop_emit_only_on_change(demo, spy):
    demo.start()                       # demo is already running
    assert spy.events == []
    demo.stop()
    demo.stop()
    assert spy.events == [("running", False)]
    assert not demo.is_running()
    demo.start()
    assert spy.events == [("running", False), ("running", True)]


def test_stop_keeps_each_toons_enabled_flag(demo):
    before = [t.enabled for t in demo.toons()]
    demo.stop()
    assert [t.enabled for t in demo.toons()] == before


def test_shutdown_stops_once(demo, spy):
    demo.shutdown()
    demo.shutdown()
    assert spy.events == [("running", False)]


def test_toggle_running(demo, spy):
    demo.toggle_running()
    demo.toggle_running()
    assert spy.events == [("running", False), ("running", True)]


def test_toggle_keep_alive_all_turns_off_those_that_are_on(demo, spy):
    demo.toggle_keep_alive_all()
    assert [t.keep_alive for t in demo.toons()] == [False] * 4
    assert spy.events == [("toon", "demo-1"), ("toon", "demo-2")]


def test_toggle_keep_alive_all_turns_everything_on_when_none_is(demo, spy):
    demo.toggle_keep_alive_all()
    spy.events.clear()
    demo.toggle_keep_alive_all()
    assert [t.keep_alive for t in demo.toons()] == [True] * 4
    assert len(spy.events) == 4


def test_toggle_keep_alive_all_does_nothing_while_unavailable(demo, spy):
    demo.set_features(keep_alive_available=False)
    spy.events.clear()
    demo.toggle_keep_alive_all()
    assert [t.keep_alive for t in demo.toons()] == [True, True, False, False]
    assert spy.events == []


def test_click_sync_state_reads_like_the_service(demo):
    assert demo.click_sync_state("demo-1") == "armed"      # the only member
    demo.set_click_sync("demo-2", True)
    assert demo.click_sync_state("demo-1") == "active"
    assert demo.click_sync_state("demo-2") == "active"
    assert demo.click_sync_state("demo-3") == "off"
    assert demo.click_sync_state("gone") == "off"
    demo.set_features(click_sync_available=False)
    assert demo.click_sync_state("demo-1") == "off"


def test_active_profile_follows_load(demo):
    assert demo.active_profile == -1
    demo.load_profile(3)
    assert demo.active_profile == 3


def test_refresh_is_recorded_and_silent(demo, spy):
    demo.refresh()
    demo.refresh()
    assert demo.refresh_count == 2
    assert spy.events == []


# ── Toons appearing, vanishing, re-slotting ────────────────────────────────

def test_add_and_remove_emit_toons_changed(demo, spy):
    extra = dataclasses.replace(demo.toon("demo-1"), window_id="demo-5", slot=4,
                                name=None)
    demo.add_toon(extra)
    assert spy.events == [("toons",)]
    assert [t.window_id for t in demo.toons()][-1] == "demo-5"
    assert demo.toon("demo-5").identity is None
    demo.remove_toon("demo-5")
    demo.remove_toon("demo-5")         # already gone: ignored
    assert spy.events == [("toons",), ("toons",)]
    with pytest.raises(ValueError):
        demo.add_toon(demo.toon("demo-1"))


def test_toons_are_ordered_by_slot_not_insertion(qapp):
    base = FakeToonSession.demo().toon("demo-1")
    session = FakeToonSession([
        dataclasses.replace(base, window_id="b", slot=2),
        dataclasses.replace(base, window_id="a", slot=0),
    ])
    assert [t.window_id for t in session.toons()] == ["a", "b"]


def test_duplicate_window_ids_are_rejected(qapp):
    base = FakeToonSession.demo().toon("demo-1")
    with pytest.raises(ValueError):
        FakeToonSession([base, base])


def test_update_reports_data_changes_as_toon_changed(demo, spy):
    demo.update_toon("demo-2", beans=90, laff=100)
    assert (demo.toon("demo-2").beans, demo.toon("demo-2").laff) == (90, 100)
    assert spy.events == [("toon", "demo-2")]
    demo.update_toon("demo-2", beans=90)           # nothing new
    assert spy.events == [("toon", "demo-2")]


def test_update_reports_a_slot_change_as_toons_changed(demo, spy):
    demo.remove_toon("demo-1")
    spy.events.clear()
    demo.update_toon("demo-2", slot=0)
    assert spy.events == [("toons",)]
    assert demo.toons()[0].window_id == "demo-2"


def test_update_with_slot_and_data_emits_both_slot_first(demo, spy):
    demo.update_toon("demo-4", slot=7, name="Renamed")
    assert spy.events == [("toons",), ("toon", "demo-4")]


def test_update_cannot_change_the_window_id(demo):
    with pytest.raises(TypeError):
        demo.update_toon("demo-1", window_id="other")
    assert demo.toon("other") is None


def test_update_of_an_unknown_window_is_ignored(demo, spy):
    demo.update_toon("gone", beans=1)
    assert spy.events == []


# ── Profiles ───────────────────────────────────────────────────────────────

def test_load_profile_applies_by_slot_and_emits_per_changed_toon(demo, spy):
    demo.set_profile(2, {
        0: {"enabled": True, "keep_alive": True},        # Flossbud: no change
        1: {"enabled": False, "keyset_id": "demo-ttr-1"},   # Hector: two fields
        3: {"enabled": True},                            # Linux: one field
        6: {"enabled": True},                            # no toon in that slot
    })
    demo.load_profile(2)
    assert demo.loaded_profiles == [2]
    assert spy.events == [("toon", "demo-2"), ("toon", "demo-4")]
    assert (demo.toon("demo-2").enabled, demo.toon("demo-2").keyset_id) == (
        False, "demo-ttr-1")
    assert demo.toon("demo-4").enabled is True


def test_load_of_an_unregistered_profile_is_recorded_and_silent(demo, spy):
    demo.load_profile(4)
    assert demo.loaded_profiles == [4]
    assert spy.events == []
