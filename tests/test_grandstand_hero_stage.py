"""Hero stage: the count lives only on Play, and blocked mode removes it."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.widgets.grandstand.hero_stage import HeroStage


@pytest.fixture
def hero(qapp):
    """Shown, because the blocked-mode contract is about VISIBILITY. On a hidden
    parent every child reports isVisible() == False, so a hidden fixture makes
    the central assertion pass vacuously."""
    h = HeroStage()
    h.resize(852, 232)
    h.show()
    qapp.processEvents()
    yield h
    h.hide()


def test_empty_party_disables_play_with_the_prompt_label(hero):
    hero.set_party([])
    assert hero.play_label() == "SELECT A TOON"
    assert hero.play_enabled() is False


def test_one_toon_is_singular(hero):
    hero.set_party(["Flossbud"])
    assert hero.play_label() == "PLAY 1 TOON"
    assert hero.play_enabled() is True


@pytest.mark.parametrize("n", [2, 3, 4])
def test_multiple_toons_are_plural_and_counted(hero, n):
    hero.set_party([f"T{i}" for i in range(n)])
    assert hero.play_label() == f"PLAY {n} TOONS"


def test_the_count_appears_nowhere_but_play(hero):
    """Handoff §4.1b: 'The count lives only on PLAY.'"""
    hero.set_party(["Flossbud", "Hiro", "Katsuro"])
    assert "3" not in hero.names_text()
    assert "3" not in hero.greeting_text()


def test_names_list_every_selected_toon(hero):
    hero.set_party(["Flossbud", "Hiro", "Katsuro"])
    assert hero.names_text() == "Flossbud · Hiro · Katsuro"


def test_empty_party_shows_the_invitation(hero):
    hero.set_party([])
    assert hero.names_text() == (
        "Choose one or more toons below to build your launch party.")


def test_greeting_uses_the_main_toon(hero):
    hero.set_main("Flossbud")
    assert "Flossbud" in hero.greeting_text()


def test_greeting_without_a_main_is_generic(hero):
    hero.set_main(None)
    assert hero.greeting_text() == "Welcome back!"


def test_play_click_emits(hero):
    hero.set_party(["Flossbud"])
    seen = []
    hero.play_clicked.connect(lambda: seen.append(1))
    hero.play_button.click()
    assert seen == [1]


def test_disabled_play_cannot_emit(hero):
    hero.set_party([])
    seen = []
    hero.play_clicked.connect(lambda: seen.append(1))
    hero.play_button.click()
    assert seen == []


def test_play_shadow_matches_the_design_and_drops_when_disabled(hero):
    """Handoff §4.1b: box-shadow 0 3px 0, and disabled Play has no shadow."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    hero.set_party(["Flossbud"])
    eff = hero.play_button.graphicsEffect()
    assert isinstance(eff, QGraphicsDropShadowEffect)
    assert eff.blurRadius() == 0
    assert (eff.xOffset(), eff.yOffset()) == (0, 3)
    hero.set_party([])
    assert hero.play_button.graphicsEffect() is None


def test_blocked_mode_removes_play_entirely(hero, qapp):
    """Spec Q6: a locked vault must not be able to dispatch anything. A disabled
    button is NOT sufficient — a locked launcher must present no launch
    affordance at all."""
    hero.set_party(["Flossbud"])
    qapp.processEvents()
    assert hero.play_button.isVisible() is True      # baseline, or the next
    assert hero.greeting.isVisible() is True         # assertions prove nothing

    hero.set_blocked("Unlock your keychain to launch.", "Unlock", lambda: None)
    qapp.processEvents()
    assert hero.is_blocked() is True
    assert hero.play_button.isVisible() is False
    assert hero.greeting.isVisible() is False
    assert hero.names.isVisible() is False
    assert hero.blocked_label.isVisible() is True
    assert hero.blocked_button.isVisible() is True
    assert "Unlock your keychain" in hero.blocked_text()


def test_unblocking_restores_every_normal_widget(hero, qapp):
    hero.set_party(["Flossbud"])
    hero.set_blocked("nope", "Unlock", lambda: None)
    qapp.processEvents()
    hero.set_blocked(None)
    qapp.processEvents()
    assert hero.is_blocked() is False
    assert hero.play_button.isVisible() is True
    assert hero.greeting.isVisible() is True
    assert hero.names.isVisible() is True
    assert hero.blocked_label.isVisible() is False
    assert hero.blocked_button.isVisible() is False
    assert hero.play_label() == "PLAY 1 TOON"


def test_blocked_action_invokes_the_callback(hero):
    called = []
    hero.set_blocked("locked", "Unlock", lambda: called.append(1))
    hero.blocked_button.click()
    assert called == [1]


def test_official_link_emits_per_game(hero):
    seen = []
    hero.official_clicked.connect(lambda: seen.append(hero.game()))
    hero.set_game("cc")
    hero.official_button.click()
    assert seen == ["cc"]


def test_official_link_copy_names_the_game(hero):
    hero.set_game("ttr")
    assert hero.official_button.text() == "Official TTR launcher"
    hero.set_game("cc")
    assert hero.official_button.text() == "Official CC launcher"


def test_missing_backdrop_falls_back_to_the_flat_base(hero, qapp):
    """Spec §7: degraded, never blank."""
    from PySide6.QtGui import QPixmap
    hero._art = {g: QPixmap() for g in ("ttr", "cc")}   # simulate load failure
    hero.set_game("cc")
    hero.repaint()                                       # must not raise
    qapp.processEvents()
