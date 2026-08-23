"""Selecting cards builds the party, greets the main, and fills the stage."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import GrandstandView


def _entry(aid, toon=None):
    return RosterEntry(account_id=aid, game="ttr", label=f"L{aid}",
                       username=f"u{aid}", toon_name=toon, species="cat",
                       dna="7400" if toon else "", accent="#4a8fe7",
                       footer="Primary", portrait_mode="render",
                       state="idle", message="", raw_error="")


@pytest.fixture
def view(qapp):
    v = GrandstandView(LaunchParty(None))
    v.resize(880, 688)
    v.set_accounts("ttr", [_entry("a", "Flossbud"), _entry("b", "Hiro"),
                           _entry("c", "Katsuro"), _entry("d", "Mochi"),
                           _entry("e", "Pip")])
    return v


def _click(view, aid):
    view.shelf.card_for(aid).clicked.emit(aid)


def test_clicking_a_card_adds_it_to_the_party(view):
    _click(view, "a")
    assert view.party().selected("ttr") == ["a"]
    assert view.hero.names_text() == "Flossbud"


def test_clicking_again_removes_it(view):
    _click(view, "a")
    _click(view, "a")
    assert view.party().selected("ttr") == []
    assert view.hero.play_enabled() is False


def test_play_label_tracks_the_party(view):
    _click(view, "a")
    _click(view, "b")
    assert view.hero.play_label() == "PLAY 2 TOONS"


def test_the_fifth_card_is_refused_and_shaken(view):
    for aid in ("a", "b", "c", "d"):
        _click(view, aid)
    shaken = []
    view.shelf.shake = lambda aid: shaken.append(aid)
    _click(view, "e")
    assert view.party().selected("ttr") == ["a", "b", "c", "d"]
    assert shaken == ["e"]


def test_the_stage_holds_four_and_follows_launch_order(view):
    for aid in ("a", "b", "c", "d"):
        _click(view, aid)
    view.shelf.card_for("c").star_clicked.emit("c")
    assert [s.account_id for s in view.hero.crew_area.slots()][0] == "c"


def test_star_sets_the_greeting(view):
    view.set_main_toon_names("ttr", {"b": "Hiro"})
    view.shelf.card_for("b").star_clicked.emit("b")
    assert "Hiro" in view.hero.greeting_text()


def test_rendering_one_game_does_not_erase_the_others_greeting(view):
    view.set_main_toon_names("ttr", {"a": "Flossbud"})
    view.shelf.card_for("a").star_clicked.emit("a")
    assert "Flossbud" in view.hero.greeting_text()

    view.set_accounts("cc", [_entry("z", "Cogsworth")])
    view.set_main_toon_names("cc", {"z": "Cogsworth"})
    assert "Flossbud" in view.hero.greeting_text()


def test_clicking_the_star_again_clears_it(view):
    view.shelf.card_for("b").star_clicked.emit("b")
    view.shelf.card_for("b").star_clicked.emit("b")
    assert view.party().star("ttr") is None
    assert view.hero.greeting_text() == "Welcome back!"


def test_star_emits_for_persistence(view):
    seen = []
    view.star_changed.connect(lambda g, a: seen.append((g, a)))
    view.shelf.card_for("b").star_clicked.emit("b")
    assert seen == [("ttr", "b")]


def test_party_change_emits(view):
    seen = []
    view.party_changed.connect(seen.append)
    _click(view, "a")
    assert seen == ["ttr"]


def test_clear_selection_empties_the_party_not_the_star(view):
    _click(view, "a")
    view.shelf.card_for("a").star_clicked.emit("a")
    view.shelf.clear_selection_clicked.emit()
    assert view.party().selected("ttr") == []
    assert view.party().star("ttr") == "a"


def test_clear_main_clears_only_the_star(view):
    _click(view, "a")
    view.shelf.card_for("a").star_clicked.emit("a")
    view.shelf.clear_main_clicked.emit()
    assert view.party().star("ttr") is None
    assert view.party().selected("ttr") == ["a"]


def test_links_disable_when_there_is_nothing_to_clear(view):
    assert view.shelf.clear_selection_link.isEnabled() is False
    assert view.shelf.clear_main_link.isEnabled() is False
    _click(view, "a")
    assert view.shelf.clear_selection_link.isEnabled() is True


def test_switching_games_keeps_each_partys_selection(view):
    _click(view, "a")
    view.set_accounts("cc", [_entry("z", "Cogsworth")])
    view.selector.game_clicked.emit("cc")
    assert view.party().selected("cc") == []
    view.selector.game_clicked.emit("ttr")
    assert view.party().selected("ttr") == ["a"]


def test_switching_games_repaints_selector_hero_and_shelf(view):
    view.set_accounts("cc", [_entry("z", "Cogsworth")])
    view.selector.game_clicked.emit("cc")
    assert view.selector.active() == "cc"
    assert view.hero.game() == "cc"
    assert [c.account_id() for c in view.shelf.cards()] == ["z"]


def test_a_toonless_selection_still_counts_on_play(view):
    view.set_accounts("ttr", [_entry("a")])          # no toon discovered
    _click(view, "a")
    assert view.hero.play_label() == "PLAY 1 TOON"
