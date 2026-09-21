"""Hero stage: the count lives only on Play, and blocked mode removes it."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QRegion
from PySide6.QtWidgets import QWidget

import utils.widgets.grandstand.crew_lineup as crew_module
from tests._render_fixtures import complete_set
from utils.widgets.grandstand.crew_lineup import (
    BUST, BUST_BOTTOM, CREW_SLOTS, CrewLineup,
)
from utils.widgets.grandstand.hero_stage import HeroStage
from utils.widgets.grandstand.model import LineupEntry


@pytest.fixture
def hero(qapp, render_cache):
    """Shown, because the blocked-mode contract is about VISIBILITY. On a hidden
    parent every child reports isVisible() == False, so a hidden fixture makes
    the central assertion pass vacuously. The stage owns a CrewLineup that
    reads the toon render cache; `render_cache` keeps that isolated."""
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


def test_lineup_is_mounted_and_reached_through_the_hero(hero):
    from utils.widgets.grandstand.crew_lineup import CrewLineup

    entry = LineupEntry(
        account_id="a", game="ttr", toon_name="A", treatment="bust",
        pose="portrait", dna="7400", icon_stem=None, species="dog",
        accent="#4a8fe7", initial="A",
    )

    hero.set_lineup([entry])

    assert isinstance(hero.crew_area, CrewLineup)
    assert [slot.account_id for slot in hero.crew_area.slots()] == ["a"]


# ── layout: the crew spans the hero (live 2026-09-21) ───────────────────────

def _lineup(aid, treatment="bust"):
    return LineupEntry(
        account_id=aid, game="ttr", toon_name=aid.title(), treatment=treatment,
        pose="portrait", dna="7400", icon_stem=None, species="dog",
        accent="#4a8fe7", initial=aid[:1].upper(),
    )


def _transparent_render(widget):
    """The widget's own paint, children included, over nothing: `grab()`
    fills the window background first, so it can never show alpha 0."""
    img = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def test_the_crew_spans_the_whole_hero(hero, qapp):
    """The crew was a child at x=352 spanning only the hero's right part, so
    a right-anchored lineup ran off its left edge. It now covers the hero and
    sits above the copy block — and Play must still take the click, which
    means the crew is transparent to the mouse (childAt skips such widgets)."""
    hero.resize(820, 232)
    qapp.processEvents()
    assert hero.crew_area.geometry() == hero.rect()
    assert hero.children()[-1] is hero.crew_area        # topmost sibling
    assert hero.crew_area.testAttribute(Qt.WA_TransparentForMouseEvents)
    play = hero.play_button
    centre = play.mapTo(hero, play.rect().center())
    assert hero.crew_area.geometry().contains(centre)   # the crew covers Play
    assert hero.childAt(centre) is play


def test_four_busts_are_never_clipped_at_the_left(hero, render_cache, qapp):
    """Live: four selected toons, the leftmost bust cut off at a vertical
    edge. CREW_SLOTS[4] right-anchors the first bust 336 px in and a bust is
    196 wide, so with the crew 820 - 352 = 468 wide its paint box began at
    -64 — inside the hero, outside the crew widget, clipped."""
    _facade, store, _pf = render_cache
    colours = {"a": "#ff0000", "b": "#0000ff", "c": "#0000ff", "d": "#0000ff"}
    for aid, colour in colours.items():
        complete_set(store, "ttr", aid.title(), "7400", colour)
    hero.resize(820, 232)
    qapp.processEvents()
    hero.set_lineup([_lineup(aid) for aid in "abcd"])
    crew = hero.crew_area
    crew.settle()
    qapp.processEvents()

    first = crew.slots()[0]
    slot_w, slot_h = first.size
    assert (first.right, slot_w) == (CREW_SLOTS[4][0], BUST[0]) == (336, 196)
    old_crew_width = 820 - 352                 # the pre-fix child at CREW_LEFT
    assert old_crew_width - first.right - slot_w == -64      # the defect
    x = crew.width() - first.right - slot_w
    assert x >= 0, f"leftmost bust starts at {x}: clipped by the crew's edge"

    y = crew.height() - slot_h - BUST_BOTTOM
    probe = crew.grab().toImage().pixelColor(int(x) + slot_w // 2,
                                             y + slot_h // 2)
    assert probe == QColor(colours["a"]), (
        f"leftmost bust's centre painted {probe.name()}, not its own render")


def test_the_crew_respects_the_hero_corners(hero, render_cache, qapp,
                                            monkeypatch):
    """A bust hangs 14 px below the floor (BUST_BOTTOM), so the right-anchored
    slot's box reaches the hero's bottom-right corner. The crew spans the hero
    now, so its square widget edge would poke out of the hero's rounded
    outline; the crew clips itself to HERO_RADIUS instead. The ±3° tilt keeps
    the real slot 4 px shy of the exact corner pixel, so this stage is
    untilted: the box must actually cover the pixel for the clip to matter."""
    monkeypatch.setattr(crew_module, "ROT", [0, 0, 0, 0])
    _facade, store, _pf = render_cache
    for aid in "abcd":
        complete_set(store, "ttr", aid.title(), "7400", "#ff0000")
    entries = [_lineup(aid) for aid in "abcd"]
    hero.resize(820, 232)
    qapp.processEvents()
    hero.set_lineup(entries)
    crew = hero.crew_area
    crew.settle()
    qapp.processEvents()
    w, h = crew.width(), crew.height()
    last = crew.slots()[-1]
    assert last.right == 0 and last.rotation == 0
    box_bottom = (h - last.size[1] - BUST_BOTTOM) + last.size[1]
    assert box_bottom > h                                # hangs below the floor

    img = _transparent_render(crew)
    assert img.pixelColor(w - 2, h - 2).alpha() == 0, (
        f"corner painted {img.pixelColor(w - 2, h - 2).name(QColor.HexArgb)}")
    inside = img.pixelColor(w - 12, h - 12)
    assert inside == QColor("#ff0000")

    # Control: the same stage with no radius (a standalone lineup's default)
    # does paint that corner pixel — so it is the clip that removed it.
    bare = CrewLineup()
    bare.resize(w, h)
    bare.set_entries(entries)
    bare.settle()
    qapp.processEvents()
    assert _transparent_render(bare).pixelColor(w - 2, h - 2) == QColor("#ff0000")
    bare.deleteLater()
