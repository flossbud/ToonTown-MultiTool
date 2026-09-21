"""LaunchParty: cap, ordering, star, pruning, persistence — no Qt involved."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.widgets.grandstand.party import CAP, LaunchParty


class FakeSettings:
    """Minimal stand-in for SettingsManager.get/set."""

    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


@pytest.fixture
def party():
    return LaunchParty(FakeSettings())


def test_cap_is_four():
    assert CAP == 4


def test_toggle_adds_and_removes(party):
    assert party.toggle("ttr", "a") is True
    assert party.selected("ttr") == ["a"]
    assert party.is_selected("ttr", "a") is True
    assert party.toggle("ttr", "a") is True
    assert party.selected("ttr") == []


def test_fifth_selection_is_rejected(party):
    for aid in ("a", "b", "c", "d"):
        assert party.toggle("ttr", aid) is True
    assert party.toggle("ttr", "e") is False
    assert party.selected("ttr") == ["a", "b", "c", "d"]


def test_deselecting_frees_a_slot(party):
    for aid in ("a", "b", "c", "d"):
        party.toggle("ttr", aid)
    party.toggle("ttr", "b")
    assert party.toggle("ttr", "e") is True
    assert party.selected("ttr") == ["a", "c", "d", "e"]


def test_selection_is_per_game(party):
    party.toggle("ttr", "a")
    assert party.selected("cc") == []
    party.toggle("cc", "z")
    assert party.selected("ttr") == ["a"]
    assert party.selected("cc") == ["z"]


def test_launch_order_puts_the_star_first(party):
    for aid in ("a", "b", "c"):
        party.toggle("ttr", aid)
    party.set_star("ttr", "c")
    assert party.launch_order("ttr") == ["c", "a", "b"]


def test_launch_order_ignores_an_unselected_star(party):
    party.toggle("ttr", "a")
    party.set_star("ttr", "zzz")
    assert party.launch_order("ttr") == ["a"]


def test_star_is_per_game_and_clearable(party):
    party.set_star("ttr", "a")
    assert party.star("ttr") == "a"
    assert party.star("cc") is None
    party.set_star("ttr", None)
    assert party.star("ttr") is None


def test_clear_empties_selection_but_keeps_the_star(party):
    party.toggle("ttr", "a")
    party.set_star("ttr", "a")
    party.clear("ttr")
    assert party.selected("ttr") == []
    assert party.star("ttr") == "a"


def test_prune_drops_deleted_accounts(party):
    for aid in ("a", "b", "c"):
        party.toggle("ttr", aid)
    party.prune("ttr", {"a", "c"})
    assert party.selected("ttr") == ["a", "c"]


def test_prune_clears_a_dangling_star(party):
    party.set_star("ttr", "gone")
    party.prune("ttr", {"a"})
    assert party.star("ttr") is None


def test_active_game_defaults_to_ttr_and_persists(party):
    assert party.active_game() == "ttr"
    party.set_active_game("cc")
    assert party.active_game() == "cc"


def test_active_game_rejects_unknown_values(party):
    party.set_active_game("nintendo")
    assert party.active_game() == "ttr"


def test_state_round_trips_through_settings():
    sm = FakeSettings()
    p1 = LaunchParty(sm)
    p1.toggle("ttr", "a")
    p1.toggle("ttr", "b")
    p1.set_star("ttr", "b")
    p1.set_active_game("cc")

    p2 = LaunchParty(sm)                      # fresh object, same store
    assert p2.selected("ttr") == ["a", "b"]
    assert p2.star("ttr") == "b"
    assert p2.active_game() == "cc"


def test_corrupt_stored_values_do_not_raise():
    sm = FakeSettings({"launcher_party_ttr": "not-a-list",
                       "launcher_star_ttr": 17,
                       "launcher_active_game": []})
    p = LaunchParty(sm)
    assert p.selected("ttr") == []
    assert p.star("ttr") is None
    assert p.active_game() == "ttr"


def test_stored_selection_is_truncated_to_the_cap():
    sm = FakeSettings({"launcher_party_ttr": ["a", "b", "c", "d", "e", "f"]})
    assert LaunchParty(sm).selected("ttr") == ["a", "b", "c", "d"]


def test_stored_duplicates_are_collapsed():
    """A repeated id would take two stage slots and launch twice."""
    sm = FakeSettings({"launcher_party_ttr": ["a", "a", "b", "a", "c"]})
    p = LaunchParty(sm)
    assert p.selected("ttr") == ["a", "b", "c"]
    assert p.launch_order("ttr") == ["a", "b", "c"]


def test_dedup_frees_slots_rather_than_consuming_them():
    sm = FakeSettings({"launcher_party_ttr": ["a", "a", "a", "a"]})
    p = LaunchParty(sm)
    assert p.selected("ttr") == ["a"]
    assert p.toggle("ttr", "b") is True      # three slots are genuinely free


def test_no_settings_manager_still_works():
    p = LaunchParty(None)
    assert p.toggle("ttr", "a") is True
    assert p.selected("ttr") == ["a"]
