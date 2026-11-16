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
