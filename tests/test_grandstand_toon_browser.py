"""Choose-a-toon browser (handoff §4.7): standing figures at `waving`, a
check on the current toon, a pick that emits and nothing more."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from tests._render_fixtures import complete_set
from utils.recent_toons import ToonRecord
from utils.toon_renders import AWAITING_RENDER_TOOLTIP
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.roster_card import CARD_H, CARD_W
from utils.widgets.grandstand.toon_browser import (
    BROWSE_POSE, EMPTY_BODY, EMPTY_TITLE, FIGURE_H, FIGURE_MAX_W, RIBBON_CHECK,
    RIBBON_PLUS, ToonBrowser, laff_line, subtitle_for, title_for,
)


def _rec(name="Flossbud", dna="7400", game="ttr", species="dog", laff=137):
    return ToonRecord(name, game, dna, laff, None, species, None)


@pytest.fixture
def browser(qapp, render_cache):
    b = ToonBrowser()
    yield b
    b.close()
    b.deleteLater()
    qapp.processEvents()


def _open(browser, toons=None, primary="Flossbud", display="Flossbud", game="ttr"):
    if toons is None:
        toons = [_rec("Flossbud", "7400"), _rec("Pepper Fizzlebounce", "7401", species="cat"),
                 _rec("Sir Wackyhopper", "7402", species="duck", laff=64)]
    browser.open(game, "a", display, toons, primary)
    return browser


def test_header_copy_is_the_handoff_string(browser):
    _open(browser)
    assert browser.title_text() == "Choose a toon · Flossbud"
    assert browser.header.title.text() == "CHOOSE A TOON · FLOSSBUD"
    assert browser.subtitle_text() == (
        "Whichever you pick is what this account shows on the launcher · 3 toons found")
    assert title_for("gag alt") == "Choose a toon · gag alt"
    assert subtitle_for(1).endswith("· 1 toon found")


def test_cards_are_shelf_sized_and_request_the_waving_pose(browser, render_cache):
    _facade, store, pf = render_cache
    store.note_dna("ttr", "Flossbud", "7400")          # discovered, not yet fetched
    _open(browser)
    cards = browser.cards()
    assert [c.toon_name() for c in cards] == [
        "Flossbud", "Pepper Fizzlebounce", "Sir Wackyhopper"]
    for card in cards:
        assert (card.width(), card.height()) == (CARD_W, CARD_H)
        assert card.requested_pose() == BROWSE_POSE == "waving"
    assert (FIGURE_H, FIGURE_MAX_W) == (132, 124)
    # A cold card asks the cache for `waving` and nothing else: the known
    # outfit is queued, the unknown one is remembered until discovery.
    key = ("ttr", "Flossbud", "7400", BROWSE_POSE)
    assert key in pf._queue or key in pf._in_flight
    assert ("ttr", "Pepper Fizzlebounce", BROWSE_POSE) in pf._pending_wants
    assert not any(k[3] != BROWSE_POSE for k in pf._queue)


def test_card_copy_lines(browser):
    _open(browser)
    card = browser.card_for("Sir Wackyhopper")
    assert card.name.text() == "Sir Wackyhopper"
    assert card.species.text() == "duck"
    assert card.laff.text() == "Laff 64"
    assert laff_line(_rec(laff=None)) == ""


def test_the_current_toon_is_checked_and_inert(browser):
    _open(browser, primary="Flossbud")
    current = browser.current_card()
    assert current is browser.card_for("Flossbud")
    assert current.is_checked() is True
    assert current.ribbon.text() == RIBBON_CHECK == "✓"
    assert browser.card_for("Pepper Fizzlebounce").ribbon.text() == RIBBON_PLUS == "+"
    seen = []
    browser.toon_picked.connect(seen.append)
    QTest.mouseClick(current, Qt.LeftButton, pos=QPoint(CARD_W // 2, CARD_H // 2))
    current.ribbon.click()
    assert seen == []


def test_without_a_primary_the_newest_is_current(browser):
    _open(browser, primary=None)
    assert browser.current_card().toon_name() == "Flossbud"      # store order


def test_picking_another_toon_emits_its_name(browser):
    _open(browser)
    seen = []
    browser.toon_picked.connect(seen.append)
    QTest.mouseClick(browser.card_for("Pepper Fizzlebounce"), Qt.LeftButton,
                     pos=QPoint(CARD_W // 2, CARD_H // 2))
    browser.card_for("Sir Wackyhopper").ribbon.click()
    assert seen == ["Pepper Fizzlebounce", "Sir Wackyhopper"]


def test_checked_card_takes_the_selected_surface(browser):
    _open(browser)
    on = gp.ribbon(True, True)["bg"].name(QColor.HexArgb)
    assert on in browser.card_for("Flossbud").ribbon.styleSheet()
    assert on not in browser.card_for("Pepper Fizzlebounce").ribbon.styleSheet()


def test_rename_ghosts_collapse_in_the_browser(browser):
    _open(browser, toons=[_rec("Katsuro", "7400"), _rec("Blue Cat", "7400"),
                          _rec("Pepper", "7401")], primary=None)
    assert [c.toon_name() for c in browser.cards()] == ["Katsuro", "Pepper"]
    assert browser.subtitle_text().endswith("· 2 toons found")


def test_empty_state_copy(browser):
    _open(browser, toons=[], primary=None, display="flossbud")
    assert browser.is_empty_state() is True
    assert browser.cards() == []
    assert browser.empty_title.text() == "No toons discovered on flossbud yet"
    assert EMPTY_TITLE == "No toons discovered on {user} yet"
    assert browser.empty_body.text() == EMPTY_BODY == (
        "Launch this account once and play a toon. The launcher records who "
        "you played, then pulls that toon's render. Until then there is "
        "nothing for it to show.")
    assert browser.empty_title.maximumWidth() <= 460
    assert browser.scroll.isVisibleTo(browser) is False
    _open(browser)
    assert browser.is_empty_state() is False
    assert browser.scroll.isVisibleTo(browser) is True


def test_card_shows_the_cached_waving_render(browser, render_cache):
    _facade, store, _pf = render_cache
    complete_set(store, "ttr", "Flossbud", "7400", "#ff0000")
    _open(browser)
    card = browser.card_for("Flossbud")
    assert card.portrait_pixmap() is not None
    assert card.toolTip() == ""


def test_a_cold_card_shows_the_silhouette_and_says_why(browser, render_cache):
    _facade, store, pf = render_cache
    store.note_dna("ttr", "Flossbud", "7400")
    _open(browser)
    card = browser.card_for("Flossbud")
    assert card.portrait_pixmap() is None
    assert card.toolTip() == AWAITING_RENDER_TOOLTIP.format(name="Flossbud")
    complete_set(store, "ttr", "Flossbud", "7400", "#00ff00")
    pf.render_landed.emit("ttr", "Flossbud", "head")           # not our pose
    assert card.portrait_pixmap() is None
    pf.render_landed.emit("ttr", "Flossbud", BROWSE_POSE)
    assert card.portrait_pixmap() is not None
    assert card.toolTip() == ""


def test_cc_toons_never_consult_the_cache(browser, render_cache, monkeypatch):
    facade, store, _pf = render_cache
    complete_set(store, "cc", "Hiro", "7400")
    asked = []
    monkeypatch.setattr(facade, "pixmap_for", lambda *a: asked.append(a))
    _open(browser, toons=[_rec("Hiro", "", "cc", "bear")], primary="Hiro", game="cc")
    assert asked == []
    assert browser.card_for("Hiro").portrait_pixmap() is None


def test_reopening_replaces_the_cards(browser):
    _open(browser)
    first = browser.cards()
    _open(browser, toons=[_rec("Solo", "9")], primary="Solo")
    assert [c.toon_name() for c in browser.cards()] == ["Solo"]
    assert all(c is not browser.cards()[0] for c in first)


def test_focus_current_lands_on_the_checked_card(browser, qapp):
    _open(browser, primary="Pepper Fizzlebounce")
    browser.show()
    qapp.processEvents()
    browser.focus_current()
    assert qapp.focusWidget() is browser.card_for("Pepper Fizzlebounce")


# ── radio keyboard (spec §4, handoff §4.7 role="radio") ─────────────────────

def test_cards_are_radio_like_with_the_keyboard(browser, qapp):
    _open(browser, primary="Flossbud")
    browser.show()
    qapp.processEvents()
    browser.focus_current()
    first, second, third = browser.cards()
    assert qapp.focusWidget() is first
    QTest.keyClick(first, Qt.Key_Right)
    assert qapp.focusWidget() is second
    QTest.keyClick(second, Qt.Key_Down)
    assert qapp.focusWidget() is third
    QTest.keyClick(third, Qt.Key_Right)                 # wraps
    assert qapp.focusWidget() is first
    QTest.keyClick(first, Qt.Key_Left)                  # wraps the other way
    assert qapp.focusWidget() is third
    QTest.keyClick(third, Qt.Key_Up)
    assert qapp.focusWidget() is second
    seen = []
    browser.toon_picked.connect(seen.append)
    QTest.keyClick(second, Qt.Key_Space)
    QTest.keyClick(third, Qt.Key_Return)
    QTest.keyClick(first, Qt.Key_Space)                 # checked: inert
    assert seen == ["Pepper Fizzlebounce", "Sir Wackyhopper"]


def test_escape_in_the_browser_is_back(browser):
    _open(browser)
    seen = []
    browser.back_requested.connect(lambda: seen.append("back"))
    QTest.keyClick(browser.cards()[0], Qt.Key_Escape)
    assert seen == ["back"]


def test_background_click_hands_focus_back_to_the_checked_card(browser, qapp):
    """M1 (re-review): StrongFocus (toon_browser.py) lets an empty browser
    take focus at all, but with cards present a click on the panel's own
    background must not strand focus there — the checked card keeps the
    arrow keys and Enter."""
    browser.resize(300, 200)
    browser.show()
    _open(browser, primary="Pepper Fizzlebounce")
    qapp.processEvents()
    browser.focus_current()
    checked = browser.card_for("Pepper Fizzlebounce")
    assert qapp.focusWidget() is checked
    QTest.mouseClick(browser, Qt.LeftButton, pos=QPoint(4, 4))   # panel bg
    assert qapp.focusWidget() is checked
    QTest.keyClick(qapp.focusWidget(), Qt.Key_Right)
    assert qapp.focusWidget() is browser.card_for("Sir Wackyhopper")


def test_the_strip_floor_grows_for_its_own_scrollbar(browser, qapp):
    """F1 (Task 6 review): CardShelf connects rangeChanged to _fit_strip
    (card_shelf.py:159) so the bar's height joins the floor once it appears;
    the browser copied the method but not the connection, so its 6px bar was
    clipped instead of pushing the scroll area's own floor down."""
    browser.resize(300, 400)
    browser.show()
    toons = [_rec(f"Toon{i}", f"74{i:02d}") for i in range(10)]
    _open(browser, toons=toons, primary="Toon0")
    qapp.processEvents()
    bar = browser.scroll.horizontalScrollBar()
    assert bar.maximum() > bar.minimum()
    assert browser.scroll.minimumHeight() >= (
        browser._strip.minimumSizeHint().height() + bar.sizeHint().height())
