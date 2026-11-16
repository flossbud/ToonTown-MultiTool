"""ToonSession: keep-alive, click sync and the feature gates.

Ported from the Multitoon tab's suites (test_keep_alive_gating.py and the
click-sync wiring it exercised) so they hold for the session too.
"""

import time

import pytest

from tests.toon_session_harness import KEEP_ALIVE_ON, FakeProfiles, Rig, profile
from utils.settings_keys import CLICK_SYNC_ENABLED


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    rigs = []

    def _make(**kwargs):
        rig = Rig(tmp_path, **kwargs)
        rigs.append(rig)
        return rig

    yield _make
    for rig in rigs:
        rig.close()


def wait_for(until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if until():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def games(monkeypatch):
    """The keep-alive dispatch asks GameRegistry which game a window is."""
    from utils.game_registry import GameRegistry
    mapping = {}
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                        lambda wid: mapping.get(str(wid), "ttr"))
    return mapping


# ── Keep-alive: the gate ───────────────────────────────────────────────────

def test_keep_alive_is_unavailable_by_default(make):
    assert make().session.keep_alive_available() is False


def test_keep_alive_needs_both_the_flag_and_consent(make):
    rig = make(settings={"keep_alive_enabled": True})
    assert rig.session.keep_alive_available() is False      # no consent recorded
    rig.settings.set("keep_alive_consent_acknowledged", True)
    assert rig.session.keep_alive_available() is True
    rig.settings.set("keep_alive_enabled", False)
    assert rig.session.keep_alive_available() is False


def test_set_keep_alive_is_ignored_while_unavailable(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.spy.events.clear()
    rig.session.set_keep_alive("a", True)
    assert rig.session.toon("a").keep_alive is False
    assert rig.spy.events == []
    assert rig.session._keep_alive_running is False


def test_set_keep_alive_works_when_available(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    assert rig.session.toon("a").keep_alive is True
    assert rig.session._keep_alive_running is True
    rig.session.set_keep_alive("a", False)
    assert rig.session._keep_alive_running is False


def test_keep_alive_can_be_turned_off_while_unavailable(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    rig.settings.set("keep_alive_enabled", False)
    rig.spy.events.clear()
    rig.session.set_keep_alive("a", False)
    assert rig.session.toon("a").keep_alive is False
    assert rig.spy.events == [("toon", "a")]


def test_switching_the_feature_off_stops_the_loop_and_keeps_the_flags(make):
    """Per-toon keep-alive is the user's setup; the master switch only says
    whether the feature runs."""
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a", "b"])
    rig.session.set_keep_alive("a", True)
    rig.session._toons["b"].rapid_fire = True
    rig.session.set_keep_alive("b", True)
    rig.spy.events.clear()

    rig.settings.set("keep_alive_enabled", False)

    assert rig.session._keep_alive_running is False
    assert [t.keep_alive for t in rig.session.toons()] == [True, True]
    assert rig.session._slot_rapid_fire == [False, True, False, False]
    assert rig.spy.events == [("features",)]


def test_switching_the_feature_on_resumes_toons_that_had_it(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    rig.settings.set("keep_alive_enabled", False)
    rig.spy.events.clear()
    rig.settings.set("keep_alive_enabled", True)
    assert rig.session._keep_alive_running is True
    assert rig.spy.events == [("features",)]


def test_switching_the_feature_on_starts_nothing_when_no_toon_has_it(make):
    rig = make(settings={"keep_alive_consent_acknowledged": True})
    rig.wm.set_windows(["a"])
    rig.settings.set("keep_alive_enabled", True)
    assert rig.session._keep_alive_running is False
    assert rig.inhibitor.calls == []


def test_a_setting_written_with_the_same_availability_announces_nothing(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.settings.set("keep_alive_enabled", True)
    rig.settings.set("theme", "dark")
    assert rig.spy.events == []


def test_load_profile_respects_the_gate(make):
    """A profile with keep-alive on, loaded while the feature is off, must not
    start the loop, and must keep the flags for when it is switched on."""
    profiles = FakeProfiles({0: profile([True] * 4, keep_alive=[True] * 4,
                                        rapid_fire=[False, True, False, False])})
    rig = make(profiles=profiles)
    rig.wm.set_windows(["a", "b"])
    rig.session.load_profile(0)
    assert rig.session._keep_alive_running is False
    assert [t.keep_alive for t in rig.session.toons()] == [True, True]
    assert rig.session._slot_rapid_fire == [False, True, False, False]
    rig.settings.set("keep_alive_consent_acknowledged", True)
    rig.settings.set("keep_alive_enabled", True)
    assert rig.session._keep_alive_running is True


def test_turning_keep_alive_off_clears_rapid_fire(make):
    profiles = FakeProfiles({0: profile([True] * 4, keep_alive=[True] * 4,
                                        rapid_fire=[True] * 4)})
    rig = make(settings=KEEP_ALIVE_ON, profiles=profiles)
    rig.wm.set_windows(["a"])
    rig.session.load_profile(0)
    assert rig.session._slot_rapid_fire[0] is True
    rig.session.set_keep_alive("a", False)
    rig.session.set_keep_alive("a", True)
    assert rig.session._slot_rapid_fire[0] is False


# ── Keep-alive: toggle all (the hotkey) ────────────────────────────────────

def test_toggle_all_turns_off_those_that_are_on(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.set_keep_alive("b", True)
    rig.session.toggle_keep_alive_all()
    assert [t.keep_alive for t in rig.session.toons()] == [False, False, False]


def test_toggle_all_turns_every_toon_on_when_none_is(make):
    rig = make(settings=KEEP_ALIVE_ON)
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.toggle_keep_alive_all()
    assert [t.keep_alive for t in rig.session.toons()] == [True, True, True]


def test_toggle_all_does_nothing_while_unavailable(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.spy.events.clear()
    rig.session.toggle_keep_alive_all()
    assert rig.session.toon("a").keep_alive is False
    assert rig.spy.events == []


# ── Keep-alive: the loop ───────────────────────────────────────────────────

FAST = {**KEEP_ALIVE_ON, "keep_alive_delay": "Rapid Fire"}       # 0.25 s cycles


def test_the_loop_sends_the_clients_key_to_toons_that_have_it(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.set_keep_alive("a", True)
    rig.session.set_keep_alive("c", True)
    assert wait_for(lambda: len(rig.input.sent) >= 2)
    assert set(rig.input.sent) == {("a", "space"), ("c", "space")}
    assert any("[KeepAlive] Sent 'Jump' to 2 toon(s)" in m for m in rig.logs)


def test_the_loop_follows_a_toon_to_its_new_slot(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a", "b"])
    rig.session.set_keep_alive("b", True)
    rig.wm.set_windows(["b"])                   # "a" closed: "b" is slot 0 now
    assert wait_for(lambda: bool(rig.input.sent))
    assert set(rig.input.sent) == {("b", "space")}


def test_the_loop_skips_a_window_with_chat_open(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a", "b"])
    rig.input.skip.add("a")
    rig.session.set_keep_alive("a", True)
    rig.session.set_keep_alive("b", True)
    assert wait_for(lambda: bool(rig.input.sent))
    assert set(rig.input.sent) == {("b", "space")}


def test_the_action_setting_picks_the_key(make, games):
    rig = make(settings={**FAST, "keep_alive_action": "book"})
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    assert wait_for(lambda: bool(rig.input.sent))
    assert rig.input.sent[0] == ("a", "Alt_L")


def test_nothing_is_sent_after_the_feature_is_switched_off(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    assert wait_for(lambda: bool(rig.input.sent))
    rig.settings.set("keep_alive_enabled", False)
    count = len(rig.input.sent)
    time.sleep(0.6)
    assert len(rig.input.sent) == count
    assert not rig.session._keep_alive_thread.is_alive()


def test_stop_halts_keep_alive_and_start_resumes_it(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    assert wait_for(lambda: bool(rig.input.sent))

    rig.session.stop()
    assert rig.session._keep_alive_running is False
    assert rig.session.toon("a").keep_alive is True        # the flag is kept
    count = len(rig.input.sent)
    time.sleep(0.6)
    assert len(rig.input.sent) == count

    rig.session.start()
    assert rig.session._keep_alive_running is True
    assert wait_for(lambda: len(rig.input.sent) > count)


def test_the_loop_ends_when_its_last_toon_closes(make, games):
    rig = make(settings=FAST)
    rig.wm.set_windows(["a", "b"])
    rig.session.set_keep_alive("a", True)
    rig.wm.set_windows(["b"])
    assert rig.session._keep_alive_running is False
    assert rig.inhibitor.calls[-1] == "release"


def test_changing_the_delay_restarts_the_cycle(make):
    rig = make(settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    rig.session._ka_cycle_start = 1.0
    rig.settings.set("keep_alive_delay", "5 min")
    assert rig.session._ka_cycle_start > 1.0


# ── Keep-alive: the sleep inhibitor ────────────────────────────────────────

def test_the_inhibitor_is_held_exactly_while_the_loop_runs(make, qapp):
    rig = make(settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.wm.set_windows(["a", "b"])
    statuses = []
    rig.session.keep_alive_inhibit_status.connect(statuses.append)

    rig.session.set_keep_alive("a", True)
    rig.session.set_keep_alive("b", True)          # second toon: no second acquire
    deadline = time.monotonic() + 3
    while not statuses and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert rig.inhibitor.calls == ["acquire"]
    assert statuses == [rig.inhibitor.status]
    assert any("Sleep inhibitor verified (fake)" in m for m in rig.logs)

    rig.session.set_keep_alive("a", False)
    assert rig.inhibitor.calls == ["acquire"]
    rig.session.set_keep_alive("b", False)
    assert rig.inhibitor.calls == ["acquire", "release"]


def test_a_late_inhibitor_result_after_release_is_dropped(make):
    rig = make(settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.wm.set_windows(["a"])
    statuses = []
    rig.session.keep_alive_inhibit_status.connect(statuses.append)
    rig.session.set_keep_alive("a", True)
    stale = rig.session._inhibit_gen
    rig.session.set_keep_alive("a", False)
    rig.session._on_inhibit_status(stale, rig.inhibitor.status)
    assert statuses == []


# ── Click sync ─────────────────────────────────────────────────────────────

@pytest.fixture
def synced(make):
    rig = make(settings={CLICK_SYNC_ENABLED: True})
    rig.wm.set_windows(["a", "b", "c"], games={"c": "cc"})
    rig.spy.events.clear()
    return rig


def test_click_sync_is_available_with_a_service_and_the_setting(make):
    assert make().session.click_sync_available() is False
    assert make(settings={CLICK_SYNC_ENABLED: True}).session.click_sync_available() is True
    assert make(settings={CLICK_SYNC_ENABLED: True},
                click_sync=False).session.click_sync_available() is False


def test_the_master_setting_reaches_the_service_and_is_announced(make):
    rig = make()
    assert rig.click_sync.enabled is False
    rig.settings.set(CLICK_SYNC_ENABLED, True)
    assert rig.click_sync.enabled is True
    assert rig.spy.events == [("features",)]
    rig.settings.set(CLICK_SYNC_ENABLED, False)
    assert rig.click_sync.enabled is False
    assert rig.spy.events == [("features",), ("features",)]


def test_set_click_sync_joins_and_leaves_the_group_by_slot(synced):
    synced.session.set_click_sync("b", True)
    assert synced.click_sync.members() == {1}
    assert synced.session.toon("b").click_sync is True
    assert synced.spy.events == [("toon", "b")]
    assert synced.session.click_sync_state("b") == "armed"
    synced.session.set_click_sync("a", True)
    assert synced.click_sync.members() == {0, 1}
    assert synced.session.click_sync_state("a") == "active"
    synced.session.set_click_sync("b", False)
    assert synced.click_sync.members() == {0}
    assert synced.session.click_sync_state("b") == "off"


def test_click_sync_is_refused_for_a_game_it_cannot_drive(synced):
    synced.session.set_click_sync("c", True)
    assert synced.session.toon("c").click_sync is False
    assert synced.click_sync.members() == set()
    assert synced.spy.events == []


def test_click_sync_is_refused_while_the_feature_is_off(make):
    rig = make()
    rig.wm.set_windows(["a"])
    rig.spy.events.clear()
    rig.session.set_click_sync("a", True)
    assert rig.session.toon("a").click_sync is False
    assert rig.spy.events == []


def test_membership_follows_the_window_when_slots_shift(synced):
    """With slot-keyed membership a closing window handed its place in the
    group to whichever window slid into its slot."""
    synced.session.set_click_sync("a", True)
    synced.wm.set_windows(["b", "c"], games={"c": "cc"})     # "a" closed
    assert synced.session.toon("b").click_sync is False
    assert synced.click_sync.members() == set()


def test_a_member_keeps_its_membership_when_it_changes_slot(synced):
    synced.session.set_click_sync("b", True)
    synced.wm.set_windows(["b", "c"], games={"c": "cc"})     # "b" is slot 0 now
    assert synced.session.toon("b").click_sync is True
    assert synced.click_sync.members() == {0}


def test_the_service_dropping_a_member_clears_the_toons_flag(synced):
    synced.session.set_click_sync("a", True)
    synced.session.set_click_sync("b", True)
    synced.spy.events.clear()
    synced.wm.window_games["b"] = "cc"          # the service can no longer drive it
    synced.click_sync.recompute()
    assert synced.session.toon("b").click_sync is False
    assert synced.session.toon("a").click_sync is True
    assert synced.spy.events == [("toon", "b")]


def test_click_sync_pauses_while_stopped_and_keeps_its_members(synced):
    synced.session.set_click_sync("a", True)
    synced.session.set_click_sync("b", True)
    synced.session.stop()
    assert synced.click_sync.enabled is False
    assert synced.click_sync.members() == {0, 1}
    assert [t.click_sync for t in synced.session.toons()] == [True, True, False]
    synced.session.start()
    assert synced.click_sync.enabled is True
    assert synced.session.click_sync_state("a") == "active"


def test_switching_the_feature_off_keeps_each_toons_choice(synced):
    synced.session.set_click_sync("a", True)
    synced.settings.set(CLICK_SYNC_ENABLED, False)
    assert synced.session.toon("a").click_sync is True
    assert synced.click_sync.members() == {0}
    assert synced.session.click_sync_state("a") == "off"


def test_window_and_geometry_changes_recompute_the_group(synced):
    synced.click_sync.calls.clear()
    synced.wm.window_geometry_updated.emit()
    assert synced.click_sync.calls == [("recompute",)]
    synced.click_sync.calls.clear()
    synced.wm.set_windows(["a", "b"])
    assert ("recompute",) in synced.click_sync.calls


def test_a_service_error_is_kept_for_the_front_end(synced):
    synced.click_sync.service_error.emit("capture died")
    assert synced.session._click_sync_error == "capture died"
