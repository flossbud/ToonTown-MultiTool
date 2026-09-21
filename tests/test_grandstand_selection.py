"""Selecting cards builds the party, greets the main, and fills the stage."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import GrandstandView


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None)


def _entry(aid, toon=None, game="ttr"):
    return RosterEntry(account_id=aid, game=game, label=f"L{aid}",
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
    assert [s.account_id for s in view.hero.crew_area.slots()] == [
        "c", "a", "b", "d"]


def test_starring_renumbers_the_ribbons_to_match_the_stage(view):
    """Handoff §4.1d: the ribbon shows the toon's stage position, and the
    star launches first (spec Q3) — so the ribbons follow launch order, not
    the order the cards were clicked in."""
    for aid in ("a", "b", "c"):
        _click(view, aid)
    assert [view.shelf.card_for(aid).ribbon_text() for aid in "abc"] == [
        "1", "2", "3"]

    view.shelf.card_for("c").star_clicked.emit("c")

    assert [s.account_id for s in view.hero.crew_area.slots()] == [
        "c", "a", "b"]
    assert [view.shelf.card_for(aid).ribbon_text() for aid in "abc"] == [
        "2", "3", "1"]

    view.shelf.card_for("c").star_clicked.emit("c")      # un-star
    assert [view.shelf.card_for(aid).ribbon_text() for aid in "abc"] == [
        "1", "2", "3"]


def test_star_sets_the_greeting(view):
    view.set_main_toon_names("ttr", {"b": "Hiro"})
    view.shelf.card_for("b").star_clicked.emit("b")
    assert "Hiro" in view.hero.greeting_text()


def test_rendering_one_game_does_not_erase_the_others_greeting(view):
    """Switching away and back must not lose the first game's names. Asserting
    without a round-trip only reads stale text: refresh() early-returns for the
    inactive game, so the hero is never repainted and the old global-map bug
    would pass."""
    view.set_main_toon_names("ttr", {"a": "Flossbud"})
    view.shelf.card_for("a").star_clicked.emit("a")
    assert "Flossbud" in view.hero.greeting_text()

    view.set_accounts("cc", [_entry("z", "Cogsworth", game="cc")])
    view.set_main_toon_names("cc", {"z": "Cogsworth"})

    view.selector.game_clicked.emit("cc")      # away...
    view.selector.game_clicked.emit("ttr")     # ...and back: forces a repaint
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
    view.set_accounts("cc", [_entry("z", "Cogsworth", game="cc")])
    view.selector.game_clicked.emit("cc")
    assert view.party().selected("cc") == []
    view.selector.game_clicked.emit("ttr")
    assert view.party().selected("ttr") == ["a"]


def test_switching_games_repaints_selector_hero_and_shelf(view):
    view.set_accounts("cc", [_entry("z", "Cogsworth", game="cc")])
    view.selector.game_clicked.emit("cc")
    assert view.selector.active() == "cc"
    assert view.hero.game() == "cc"
    assert [c.account_id() for c in view.shelf.cards()] == ["z"]


def test_card_actions_emit_view_intents_for_the_active_game(view):
    got = []
    view.launch_requested.connect(lambda g, a: got.append(("launch", g, a)))
    view.cancel_requested.connect(lambda g, a: got.append(("cancel", g, a)))
    view.quit_requested.connect(lambda g, a: got.append(("quit", g, a)))
    view.enter_2fa_requested.connect(lambda g, a: got.append(("2fa", g, a)))
    view.retry_requested.connect(lambda g, a: got.append(("retry", g, a)))
    view.shelf.launch_clicked.emit("a")
    view.shelf.cancel_clicked.emit("a")
    view.shelf.quit_clicked.emit("a")
    view.shelf.enter_2fa_clicked.emit("a")
    view.shelf.retry_clicked.emit("a")
    assert got == [("launch", "ttr", "a"), ("cancel", "ttr", "a"),
                   ("quit", "ttr", "a"), ("2fa", "ttr", "a"),
                   ("retry", "ttr", "a")]


def test_account_state_routes_only_for_the_active_game(view):
    view.set_account_state("cc", "a", "running")
    assert view.shelf.card_for("a").state() == "idle"
    view.set_account_state("ttr", "a", "queued", "position 42", "raw")
    card = view.shelf.card_for("a")
    assert card.state() == "queued"
    assert card.footer_text() == "In queue · position 42"
    assert card.raw_error() == "raw"


def test_a_toonless_selection_still_counts_on_play(view):
    view.set_accounts("ttr", [_entry("a")])          # no toon discovered
    _click(view, "a")
    assert view.hero.play_label() == "PLAY 1 TOON"
