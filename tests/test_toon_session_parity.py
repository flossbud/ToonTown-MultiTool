"""Behaviour the session must share with the Multitoon tab it replaces.

Each test here pins something the tab did that the first port did not.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

from tests.toon_session_harness import KEEP_ALIVE_ON, FakeProfiles, Rig, profile


@pytest.fixture
def make(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    rigs = []

    def _make(**kwargs):
        rig = Rig(tmp_path, **kwargs)
        rigs.append(rig)
        return rig

    yield _make
    for rig in rigs:
        rig.close()


# ── Profiles: autosave ──────────────────────────────────────────────────────

FOUR_TOONS = dict(enabled=[True, True, True, True],
                  modes=["Default", "Arrows", "Third", "Third"],
                  keep_alive=[False, False, True, False],
                  rapid_fire=[False, False, True, False])


def test_autosave_keeps_what_the_profile_holds_for_slots_with_no_toon(make):
    """A four-toon profile loaded with two toons running: changing one of
    them must not write defaults over the other two slots. The tab kept
    those slots' keysets in its selectors and saved them back unchanged."""
    profiles = FakeProfiles({0: profile(**FOUR_TOONS)})
    rig = make(windows=["a", "b"], profiles=profiles)
    rig.session.load_profile(0)
    rig.session.set_enabled("a", False)
    index, enabled, modes, keep_alive, rapid_fire = profiles.saved[-1]
    assert index == 0
    assert enabled == [False, True, True, True]         # slot 0 changed, 2 and 3 kept
    assert modes == ["Default", "Arrows", "Third", "Third"]
    assert keep_alive == [False, False, True, False]
    assert rapid_fire == [False, False, True, False]


def test_autosave_still_writes_every_slot_that_has_a_toon(make):
    profiles = FakeProfiles({0: profile(**FOUR_TOONS)})
    rig = make(windows=["a", "b", "c", "d"], profiles=profiles)
    rig.session.load_profile(0)
    rig.session.set_keyset("d", "t0")
    _index, enabled, modes, keep_alive, _rapid = profiles.saved[-1]
    assert modes == ["Default", "Arrows", "Third", "Default"]
    assert enabled == [True, True, True, True]
    assert keep_alive == [False, False, True, False]


def test_autosave_without_a_readable_profile_writes_defaults_for_empty_slots(make):
    """A profile store that cannot give the stored values back (first save
    of a slot) must not stop the save."""
    class Unreadable(FakeProfiles):
        def get_profile(self, index):
            if self.saved or getattr(self, "loaded", False):
                raise KeyError(index)
            self.loaded = True
            return profile([True, True, False, False])

    profiles = Unreadable()
    rig = make(windows=["a"], profiles=profiles)
    rig.session.load_profile(0)
    rig.session.set_enabled("a", False)
    _index, enabled, modes, _ka, _rf = profiles.saved[-1]
    assert enabled == [False, False, False, False]
    assert len(modes) == 4


# ── Keep-alive: the first cycle waits a full interval ───────────────────────

@pytest.fixture
def games(monkeypatch):
    """Every window is a Toontown window, as far as keep-alive can tell."""
    from utils.game_registry import GameRegistry
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                        lambda wid: "ttr", raising=False)


def keep_alive_lines(rig):
    return [line for line in rig.logs if line.startswith("[KeepAlive] ")
            and "inhibitor" not in line]


def test_a_toon_poll_does_not_bring_the_first_keep_alive_forward(make, games, qapp):
    """Keep-alive set to 30 s must not press its key a few seconds after it
    is switched on. The toon poll publishes every 5 s; publishing used to
    wake the loop, and a loop that has not fired yet fires on any wake."""
    rig = make(windows=["a"],
               settings={**KEEP_ALIVE_ON, "keep_alive_delay": "30 sec"})
    rig.session.set_keep_alive("a", True)
    time.sleep(0.2)
    rig.ttr("a", "Flossbud", beans=5)           # what each poll does
    rig.ttr("a", "Flossbud", beans=6)
    time.sleep(0.4)
    assert rig.input.sent == []
    assert keep_alive_lines(rig) == []


def test_a_changed_interval_still_restarts_the_cycle_at_once(make, games, qapp):
    """The tab woke the loop when the interval or the action changed, and a
    loop that has not fired yet fires then. Kept as it was."""
    rig = make(windows=["a"],
               settings={**KEEP_ALIVE_ON, "keep_alive_delay": "30 sec"})
    rig.session.set_keep_alive("a", True)
    time.sleep(0.2)
    rig.settings.set("keep_alive_delay", "10 sec")
    deadline = time.monotonic() + 2.0
    while not rig.input.sent and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert [wid for wid, _key in rig.input.sent] == ["a"]


def test_switching_rapid_fire_wakes_the_loop(make, games, qapp):
    """A profile that turns rapid fire on for a toon already on keep-alive
    must take effect now, not after the long interval the loop is sleeping."""
    profiles = FakeProfiles({0: profile([True], keep_alive=[True], rapid_fire=[True])})
    rig = make(windows=["a"], profiles=profiles,
               settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.session.set_keep_alive("a", True)
    time.sleep(0.2)
    rig.session.load_profile(0)
    deadline = time.monotonic() + 3.0
    while not rig.input.sent and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert rig.input.sent, "rapid fire did not start within 3 s"


# ── Profiles: a window that appears after the load ──────────────────────────

LATE = dict(enabled=[True, True, False, True],
            modes=["Default", "Arrows", "Third", "Third"],
            keep_alive=[False, False, True, False],
            rapid_fire=[False, False, False, False])


def test_a_window_that_appears_under_a_profile_takes_its_slot(make):
    """The tab set all four selectors on load, so a toon started later came
    up on the profile's keyset. Here it takes keyset, keep-alive and enabled
    from its slot."""
    profiles = FakeProfiles({0: profile(**LATE)})
    rig = make(windows=["a", "b"], profiles=profiles, settings=KEEP_ALIVE_ON)
    rig.session.load_profile(0)
    rig.wm.set_windows(["a", "b", "c"])
    third = rig.session.toon("c")
    assert third.keyset_id == "t2"                 # "Third"
    assert third.keep_alive is True
    assert third.enabled is False                  # the profile has slot 3 off
    rig.wm.set_windows(["a", "b", "c", "d"])
    fourth = rig.session.toon("d")
    assert (fourth.keyset_id, fourth.keep_alive, fourth.enabled) == ("t2", False, True)


def test_the_next_autosave_leaves_that_slot_as_the_profile_had_it(make):
    profiles = FakeProfiles({0: profile(**LATE)})
    rig = make(windows=["a", "b"], profiles=profiles, settings=KEEP_ALIVE_ON)
    rig.session.load_profile(0)
    rig.wm.set_windows(["a", "b", "c"])
    rig.session.set_enabled("a", False)            # any save point
    _index, enabled, modes, keep_alive, _rapid = profiles.saved[-1]
    assert modes == ["Default", "Arrows", "Third", "Third"]
    assert keep_alive == [False, False, True, False]
    assert enabled == [False, True, False, True]   # only slot 1 changed


def test_under_a_profile_the_remembered_keyset_does_not_apply(make):
    """Per-toon memory is for when no profile is in force."""
    profiles = FakeProfiles({0: profile(**LATE)})
    rig = make(windows=["a", "b"], profiles=profiles)
    rig.prefs.update("ttr::Daisy", keyset_id="t1")
    rig.session.load_profile(0)
    rig.wm.set_windows(["a", "b", "c"])
    rig.ttr("c", "Daisy")
    assert rig.session.toon("c").keyset_id == "t2"
    # A toon that was already running sits on its profile keyset too, even
    # when that is the default and its name arrives afterwards.
    rig.prefs.update("ttr::Flossbud", keyset_id="t1")
    rig.ttr("a", "Flossbud")
    assert rig.session.toon("a").keyset_id == "t0"


def test_without_a_profile_a_new_window_starts_enabled_on_its_own_keyset(make):
    rig = make(windows=["a"])
    rig.prefs.update("ttr::Daisy", keyset_id="t1")
    rig.wm.set_windows(["a", "b"])
    new = rig.session.toon("b")
    assert (new.enabled, new.keep_alive, new.keyset_id) == (True, False, "t0")
    rig.ttr("b", "Daisy")
    assert rig.session.toon("b").keyset_id == "t1"      # remembered, no profile


def test_a_profile_set_the_new_toons_game_lacks_leaves_it_on_its_default(make):
    """Slot 3 names a Toontown set; a Corporate Clash window lands there."""
    profiles = FakeProfiles({0: profile(**LATE)})
    rig = make(windows=["a", "b"], profiles=profiles)
    rig.session.load_profile(0)
    rig.wm.set_windows(["a", "b", "c"], games={"c": "cc"})
    assert rig.session.toon("c").keyset_id == "c0"
    assert rig.session.toon("c").enabled is False       # the rest of the slot applies


def test_a_different_toon_in_the_same_window_goes_back_to_the_profile_keyset(make):
    profiles = FakeProfiles({0: profile(**LATE)})
    rig = make(windows=["a", "b"], profiles=profiles)
    rig.session.load_profile(0)
    rig.ttr("b", "Hector")
    assert rig.session.toon("b").keyset_id == "t1"      # "Arrows"
    rig.ttr("b", "Linux")                               # logged out, other toon
    assert rig.session.toon("b").keyset_id == "t1"


# ── Profiles: keep-alive never comes back on by itself ──────────────────────

class StoredProfiles(FakeProfiles):
    """A profile store that gives back what was saved, like the real one."""

    def save_profile(self, index, enabled_toons, movement_modes,
                     keep_alive=None, rapid_fire=None):
        super().save_profile(index, enabled_toons, movement_modes,
                             keep_alive=keep_alive, rapid_fire=rapid_fire)
        self.profiles[index] = profile(enabled_toons, movement_modes,
                                       keep_alive, rapid_fire)


def test_keep_alive_switched_off_under_a_profile_stays_off_after_a_refresh(make):
    profiles = StoredProfiles({0: profile([True, True], keep_alive=[True, True])})
    rig = make(windows=["a", "b"], profiles=profiles, settings=KEEP_ALIVE_ON)
    rig.session.load_profile(0)
    assert rig.session.toon("a").keep_alive is True
    rig.session.set_keep_alive("a", False)
    assert profiles.profiles[0].keep_alive[:2] == [False, True]   # the profile says off
    rig.session.refresh()                    # drops every window ...
    assert rig.session.toons() == []
    rig.wm.set_windows(["a", "b"])           # ... and the poll loop finds them again
    assert rig.session.toon("a").keep_alive is False
    assert rig.session.toon("b").keep_alive is True


def test_the_keep_alive_hotkey_is_a_save_point_too(make):
    profiles = StoredProfiles({0: profile([True, True], keep_alive=[True, False])})
    rig = make(windows=["a", "b"], profiles=profiles, settings=KEEP_ALIVE_ON)
    rig.session.load_profile(0)
    rig.session.toggle_keep_alive_all()      # one is on: turn those off
    assert profiles.profiles[0].keep_alive[:2] == [False, False]
    rig.session.toggle_keep_alive_all()      # none on: turn all on
    assert profiles.profiles[0].keep_alive[:2] == [True, True]


def test_keep_alive_toggle_saves_nothing_without_a_profile(make):
    profiles = StoredProfiles()
    rig = make(windows=["a"], profiles=profiles, settings=KEEP_ALIVE_ON)
    rig.session.set_keep_alive("a", True)
    assert profiles.saved == []
