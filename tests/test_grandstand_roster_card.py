"""Roster card identity: portrait pose, controls, selection, star."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.model import CARD_POSE, RosterEntry
from utils.widgets.grandstand.roster_card import (
    CARD_H, CARD_W, HEAD_FIT, RosterCard,
)


@pytest.fixture
def no_network(monkeypatch):
    """Exercise the real fetcher integration while isolating its external HTTP
    boundary — same pattern as tests/test_grandstand_crew_lineup.py. Tests that
    care about cache hits or requests override these themselves."""
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None)


def _entry(aid="a", *, toon="Flossbud", species="cat", game="ttr",
           footer="Primary", mode="render", state="idle"):
    return RosterEntry(
        account_id=aid, game=game, label="Gag alt", username="flossbud",
        toon_name=toon, species=species, dna="7400" if toon else "",
        accent="#4a8fe7", footer=footer, portrait_mode=mode,
        state=state, message="", raw_error="")


@pytest.fixture
def card(qapp, no_network):
    c = RosterCard()
    c.set_entry(_entry())
    return c


@pytest.fixture
def hosted(qapp, no_network):
    """A card owned by a parent, the way the shelf owns it.

    A standalone top-level card cannot express a resting state offscreen: Qt
    activates it on show() AND the offscreen cursor sits at the origin, inside
    a card mapped to (2,2). Both conditions legitimately reveal the controls
    (handoff §4.1d hover, §5 focus), so the widget is right and an unhosted
    assertion is simply unobservable. Host it and park focus on a sibling.
    """
    host = QWidget()
    host.resize(420, 420)
    sink = QPushButton("focus sink", host)   # someone else must own focus
    sink.move(0, 0)
    c = RosterCard(host)
    c.set_entry(_entry())
    c.move(240, 180)                         # clear of the cursor's origin
    host.show()
    qapp.processEvents()
    sink.setFocus()
    qapp.processEvents()
    yield c
    host.close()
    host.deleteLater()
    qapp.processEvents()


def test_fixed_card_geometry(card):
    assert (CARD_W, CARD_H) == (148, 216)
    assert card.size().width() == CARD_W
    assert card.size().height() == CARD_H


def test_shows_the_toon_name_and_username(card):
    assert card.name_text() == "Flossbud"
    assert card.user_text() == "flossbud"


def test_falls_back_to_the_label_when_there_is_no_toon(qapp):
    c = RosterCard()
    c.set_entry(_entry(toon=None, footer="No toon yet", mode="waiting"))
    assert c.name_text() == "Gag alt"
    assert c.footer_text() == "No toon yet"


def test_cards_always_request_the_head_pose(card):
    """Handoff §4.1d: the shelf reads as one uniform row, whatever pose each
    toon has saved."""
    assert card.requested_pose() == CARD_POSE == "head"


def test_head_fit_covers_the_species_the_handoff_lists():
    for species in ("cat", "dog", "duck", "mouse", "rabbit", "horse",
                    "monkey", "bear", "pig", "deer", "crocodile"):
        assert species in HEAD_FIT
    assert HEAD_FIT["dog"] == (1.08, 11)


def test_unknown_species_gets_a_neutral_fit(card):
    assert card.head_fit_for("wombat") == (1.0, 0)


def test_selection_toggles_and_reports(card):
    assert card.is_selected() is False
    card.set_selected(True)
    assert card.is_selected() is True


def test_position_badge_shows_stage_place(card):
    card.set_selected(True)
    card.set_position(3)
    assert card.ribbon_text() == "3"


def test_unselected_ribbon_is_a_plus(card):
    card.set_selected(False)
    card.set_position(None)
    assert card.ribbon_text() == "+"


def test_body_click_emits_with_the_account_id(card):
    seen = []
    card.clicked.connect(seen.append)
    QTest.mouseClick(card, Qt.LeftButton, pos=QPoint(CARD_W // 2, CARD_H // 2))
    assert seen == ["a"]


def test_star_click_does_not_also_select(card):
    """Handoff §4.1d: the star needs stopPropagation against the card."""
    body, stars = [], []
    card.clicked.connect(body.append)
    card.star_clicked.connect(stars.append)
    QTest.mouseClick(card.star, Qt.LeftButton, pos=QPoint(6, 6))
    assert stars == ["a"]
    assert body == []


def test_pencil_and_gear_emit_their_own_intents(card):
    edits, gears = [], []
    card.edit_clicked.connect(edits.append)
    card.gear_clicked.connect(gears.append)
    QTest.mouseClick(card.pencil, Qt.LeftButton, pos=QPoint(6, 6))
    QTest.mouseClick(card.gear, Qt.LeftButton, pos=QPoint(6, 6))
    assert edits == ["a"] and gears == ["a"]


def test_pencil_and_gear_are_hidden_until_hover(hosted, qapp):
    assert hosted.controls_revealed() is False
    hosted.enterEvent(None)
    assert hosted.controls_revealed() is True
    hosted.leaveEvent(None)
    assert hosted.controls_revealed() is False


def test_focus_also_reveals_the_controls(hosted, qapp):
    """Hover-only controls must be keyboard-reachable (handoff §5)."""
    hosted.setFocus()
    qapp.processEvents()
    assert hosted.controls_revealed() is True


def test_the_chips_are_in_the_tab_order(hosted):
    """focusPolicy is what makes Tab reach these controls at all. It cannot be
    inferred from setFocus(), which bypasses the policy entirely."""
    assert hosted.pencil.focusPolicy() == Qt.TabFocus
    assert hosted.gear.focusPolicy() == Qt.TabFocus


def test_tab_from_the_card_reaches_one_of_its_own_controls(hosted, qapp):
    """Tab from the focused card must land on a control the card owns, not skip
    past it to the next widget in the window."""
    hosted.setFocus()
    qapp.processEvents()
    assert hosted.focusNextChild() is True
    landed = QApplication.focusWidget()
    assert landed is not None and hosted.isAncestorOf(landed)


def test_tabbing_from_the_card_to_a_chip_keeps_the_controls_revealed(hosted, qapp):
    """Focus moving card -> pencil is movement WITHIN the card, not away."""
    hosted.setFocus()
    qapp.processEvents()
    assert hosted.controls_revealed() is True
    hosted.pencil.setFocus()
    qapp.processEvents()
    assert hosted.pencil.hasFocus() is True
    assert hosted.controls_revealed() is True


def test_action_stays_revealed_as_focus_moves_within_card(hosted, qapp):
    """The action belongs to the same focus cluster as pencil and gear."""
    hosted.set_state("idle")
    hosted.set_selected(False)
    assert hosted.action_visible() is False
    hosted.setFocus()
    qapp.processEvents()
    assert hosted.action_visible() is True
    hosted.pencil.setFocus()
    qapp.processEvents()
    assert hosted.pencil.hasFocus() is True
    assert hosted.action_visible() is True


def test_keyboard_can_trigger_the_pencil_and_gear(hosted, qapp):
    """Handoff §5: revealing a control is worthless if only a mouse can use it.

    `hasFocus()` confirms that each revealed chip accepted programmatic focus
    before activation. Tab reachability is pinned separately: `setFocus()` and
    `keyClick` both bypass focus policy and cannot prove tab order themselves.
    """
    edits, gears = [], []
    hosted.edit_clicked.connect(edits.append)
    hosted.gear_clicked.connect(gears.append)

    # The card's own focus is what reveals the chips; a hidden chip cannot be
    # focused.
    hosted.setFocus()
    qapp.processEvents()
    hosted.pencil.setFocus()
    qapp.processEvents()
    assert hosted.pencil.hasFocus() is True      # reachable
    QTest.keyClick(hosted.pencil, Qt.Key_Space)  # and activatable

    hosted.gear.setFocus()
    qapp.processEvents()
    assert hosted.gear.hasFocus() is True
    QTest.keyClick(hosted.gear, Qt.Key_Space)

    assert edits == ["a"] and gears == ["a"]


def test_the_action_is_in_the_tab_order(hosted):
    """A full party refuses Space on a fifth card, so the visible per-card
    Launch is the only keyboard route for accounts 5-16. It must be reachable
    the same way the pencil and gear are."""
    assert hosted.action.focusPolicy() == Qt.TabFocus


def test_tab_walks_from_the_card_to_its_action_before_leaving(hosted, qapp):
    """Traversal, not policy: repeated Tab from the focused card must land on
    the action while still inside the card. `setFocus()` cannot show this."""
    hosted.set_state("idle")
    hosted.set_selected(False)
    hosted.setFocus()
    qapp.processEvents()
    landings = []
    for _ in range(8):
        assert hosted.focusNextChild() is True
        qapp.processEvents()
        focused = QApplication.focusWidget()
        if not hosted.isAncestorOf(focused):
            break
        landings.append(focused)
    assert hosted.action in landings


@pytest.mark.parametrize("state,signal_name", [
    ("idle", "launch_clicked"),
    ("failed", "retry_clicked"),
])
@pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Return])
def test_keyboard_can_trigger_the_action(hosted, qapp, state, signal_name, key):
    """Space and Return on the focused action fire the state's own signal —
    and only that. Return must not fall through to the card body, whose own
    Return toggles selection."""
    seen, toggled = [], []
    getattr(hosted, signal_name).connect(seen.append)
    hosted.clicked.connect(toggled.append)
    hosted.set_state(state)
    hosted.set_selected(False)

    hosted.setFocus()                            # reveals the action
    qapp.processEvents()
    hosted.action.setFocus()
    qapp.processEvents()
    assert hosted.action.hasFocus() is True
    QTest.keyClick(hosted.action, key)

    assert seen == ["a"]
    assert toggled == []


def test_focus_on_the_action_keeps_it_revealed_until_focus_leaves(hosted, qapp):
    """The action is the last stop in the card's focus cluster. Landing on it
    must not read as leaving the card; leaving it for another widget must."""
    hosted.set_state("idle")
    hosted.set_selected(False)
    hosted.setFocus()
    qapp.processEvents()
    hosted.gear.setFocus()
    qapp.processEvents()
    hosted.action.setFocus()
    qapp.processEvents()
    assert hosted.action.hasFocus() is True
    assert hosted.action_visible() is True
    assert hosted.controls_revealed() is True

    hosted.parentWidget().findChild(QPushButton).setFocus()   # the focus sink
    qapp.processEvents()
    assert hosted.action_visible() is False
    assert hosted.controls_revealed() is False


def test_focus_leaving_the_card_entirely_hides_the_controls(hosted, qapp):
    # The card's own focus is what reveals the chips; a hidden chip cannot be
    # focused.
    hosted.setFocus()
    qapp.processEvents()
    hosted.pencil.setFocus()
    qapp.processEvents()
    assert hosted.controls_revealed() is True
    hosted.parentWidget().findChild(QPushButton).setFocus()   # the focus sink
    qapp.processEvents()
    assert hosted.controls_revealed() is False


def test_focus_moving_from_the_card_straight_out_hides_the_controls(hosted, qapp):
    """Focus leaving the card without passing through a chip. Qt has already
    moved the application focus widget when FocusOut is delivered, so the
    synchronous refresh must observe the external owner and hide controls."""
    hosted.setFocus()
    qapp.processEvents()
    assert hosted.controls_revealed() is True
    hosted.parentWidget().findChild(QPushButton).setFocus()   # the focus sink
    qapp.processEvents()
    assert hosted.controls_revealed() is False


def test_keyboard_activates_selection(card, qapp):
    seen = []
    card.clicked.connect(seen.append)
    card.show()
    qapp.processEvents()
    QTest.keyClick(card, Qt.Key_Space)
    assert seen == ["a"]


def test_starred_state_reports(card):
    card.set_starred(True)
    assert card.is_starred() is True


def test_species_card_paints_a_silhouette(qapp, no_network):
    """The fallback must actually draw. Rendering with a species and without
    one must differ; deleting the paint_race_silhouette call makes them equal."""
    from utils.cc_race_assets import asset_stem_for_species
    assert asset_stem_for_species("bear")      # the fallback needs a real asset

    def render(species):
        c = RosterCard()
        c.set_entry(_entry(game="cc", species=species, mode="species"))
        pm = QPixmap(CARD_W, CARD_H)
        pm.fill(Qt.black)
        c.render(pm)
        return pm.toImage()

    assert render("bear") != render(None)


def test_controls_are_seeded_before_any_setter_runs(qapp):
    """A freshly built card already reads '+' and a hollow star."""
    c = RosterCard()
    assert c.ribbon_text() == "+"
    assert c.star.text() == "☆"


def test_card_body_is_a_vertical_wash_not_a_flat_fill(card):
    """Handoff §4.1d: linear-gradient(180deg, {accent} 26%, rgba(0,0,0,.3)).
    A flat fill of the top stop makes these two samples identical."""
    pm = QPixmap(CARD_W, CARD_H)
    pm.fill(Qt.black)
    card.render(pm)
    img = pm.toImage()
    top = img.pixelColor(CARD_W // 2, 4)
    bottom = img.pixelColor(CARD_W // 2, CARD_H - 4)
    assert top != bottom
    assert top.blue() > bottom.blue()


def test_selected_ribbon_takes_the_palette_blue(card):
    """Handoff §4.1d: 'Ribbon selected: bg --blue, border --blue-border'.
    The ribbon has its own palette entry; it is not a control chip."""
    blue = gp.ribbon(True, True)["bg"].name(QColor.HexArgb)
    card.set_selected(True)
    assert blue in card.ribbon.styleSheet()
    card.set_selected(False)
    assert blue not in card.ribbon.styleSheet()


def test_star_is_gold_only_while_it_marks_the_main(card):
    card.set_starred(True)
    assert gp.card_star(True, True)["ink"].name() in card.star.styleSheet()
    card.set_starred(False)
    assert gp.card_star(False, True)["ink"].name() in card.star.styleSheet()


def test_pencil_and_gear_brighten_on_their_own_hover(card):
    """Handoff §4.1d: hover bg rgba(0,0,0,.55), icon #fff."""
    card.pencil.enterEvent(None)
    assert gp.control_chip(True, True)["ink"].name() in card.pencil.styleSheet()
    card.pencil.leaveEvent(None)
    assert gp.control_chip(True, True)["ink"].name() not in card.pencil.styleSheet()


def test_render_mode_requests_the_head_pose_on_a_cache_miss(qapp, monkeypatch):
    asked = []
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: asked.append((dna, pose)))
    c = RosterCard()
    c.set_entry(_entry())
    assert asked == [("7400", CARD_POSE)]


def test_a_cached_portrait_is_used_without_a_request(qapp, monkeypatch):
    """The synchronous cache-hit branch: no fetch, pixmap available at once."""
    hit = QPixmap(16, 16)
    hit.fill(Qt.blue)
    asked = []
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: hit)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: asked.append(dna))
    c = RosterCard()
    c.set_entry(_entry())
    assert asked == []
    assert c.portrait_pixmap() is hit


def test_species_mode_never_fetches_a_rendition(qapp, monkeypatch):
    """A Corporate Clash account carries a dna but paints its species
    silhouette — `model.portrait_mode` already rules that (Task 4), and
    `lineup_entries` branches on the same field. The card must agree."""
    asked = []
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: asked.append(dna))
    c = RosterCard()
    c.set_entry(_entry(game="cc", species="bear", mode="species"))
    assert asked == []
    assert c.portrait_pixmap() is None


def test_a_late_pose_reply_is_ignored_in_species_mode(qapp, no_network):
    """The fetcher is a shared singleton, so a reply for this dna can arrive
    at a card whose entry no longer wants a rendition."""
    c = RosterCard()
    c.set_entry(_entry(game="cc", species="bear", mode="species"))
    pm = QPixmap(8, 8)
    pm.fill(Qt.red)
    c._on_pose_ready("7400", CARD_POSE, pm)
    assert c.portrait_pixmap() is None
