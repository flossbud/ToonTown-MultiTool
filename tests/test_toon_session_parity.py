"""Behaviour the session must share with the Multitoon tab it replaces.

Each test here pins something the tab did that the first port did not.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.toon_session_harness import FakeProfiles, Rig, profile


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
