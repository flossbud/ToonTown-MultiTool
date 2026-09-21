"""Card shelf: one card per account, an Add tile, head-row links."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

import utils.motion as motion
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.card_shelf import HEAD_H, CardShelf
from utils.widgets.grandstand.model import RosterEntry


@pytest.fixture(autouse=True)
def _isolated_renders(render_cache):
    """Every card asks the toon render cache for a head pose. `render_cache`
    (tests/conftest.py) installs an isolated cache whose downloads never run."""


def _entry(aid):
    return RosterEntry(account_id=aid, game="ttr", label=f"L{aid}",
                       username=f"u{aid}", toon_name=f"T{aid}", species="cat",
                       dna="7400", accent="#4a8fe7", footer="Primary",
                       portrait_mode="render", state="idle", message="",
                       raw_error="")


@pytest.fixture
def shelf(qapp):
    s = CardShelf()
    s.resize(852, 300)
    return s


def test_one_card_per_account(shelf):
    shelf.set_entries([_entry("a"), _entry("b"), _entry("c")])
    assert [c.account_id() for c in shelf.cards()] == ["a", "b", "c"]


def test_add_tile_is_always_last(shelf):
    """Not just present — *after* every card, and still after a rebuild that
    inserts new cards ahead of it."""
    shelf.set_entries([_entry("a"), _entry("b")])
    assert shelf.add_tile.isVisibleTo(shelf)
    assert shelf.strip_widgets() == ["a", "b", shelf.add_tile]
    shelf.set_entries([_entry("c"), _entry("d"), _entry("e")])
    assert shelf.strip_widgets() == ["c", "d", "e", shelf.add_tile]


def test_empty_roster_shows_only_the_add_tile(shelf):
    shelf.set_entries([])
    assert shelf.cards() == []
    assert shelf.add_tile.isVisibleTo(shelf)


def test_rebuilding_reuses_nothing_stale(shelf):
    shelf.set_entries([_entry("a"), _entry("b")])
    shelf.set_entries([_entry("b")])
    assert [c.account_id() for c in shelf.cards()] == ["b"]
    assert shelf.card_for("a") is None


def test_selection_marks_cards_and_numbers_them(shelf):
    """The shelf numbers the list it is handed, in that order: the caller
    passes the stage order (LaunchParty.launch_order, star first). The star
    id here is decoration only — the shelf never reorders around it."""
    shelf.set_entries([_entry("a"), _entry("b"), _entry("c")])
    shelf.set_selection(["c", "a"], star_id="a")
    assert shelf.card_for("c").is_selected() is True
    assert shelf.card_for("c").ribbon_text() == "1"
    assert shelf.card_for("a").ribbon_text() == "2"
    assert shelf.card_for("b").is_selected() is False
    assert shelf.card_for("b").ribbon_text() == "+"


def test_star_marks_exactly_one_card(shelf):
    shelf.set_entries([_entry("a"), _entry("b")])
    shelf.set_selection([], star_id="b")
    assert shelf.card_for("b").is_starred() is True
    assert shelf.card_for("a").is_starred() is False


def test_links_disable_when_there_is_nothing_to_clear(shelf):
    shelf.set_links_enabled(clear_selection=False, clear_main=False)
    assert shelf.clear_selection_link.isEnabled() is False
    assert shelf.clear_main_link.isEnabled() is False


def test_head_row_links_emit(shelf):
    seen = []
    shelf.clear_selection_clicked.connect(lambda: seen.append("sel"))
    shelf.clear_main_clicked.connect(lambda: seen.append("main"))
    shelf.manage_clicked.connect(lambda: seen.append("manage"))
    shelf.set_links_enabled(clear_selection=True, clear_main=True)
    shelf.clear_selection_link.click()
    shelf.clear_main_link.click()
    shelf.manage_link.click()
    assert seen == ["sel", "main", "manage"]


def test_add_tile_emits(shelf):
    seen = []
    shelf.add_account_clicked.connect(lambda: seen.append(1))
    shelf.set_entries([])
    shelf.add_tile.click()
    assert seen == [1]


def test_card_signals_are_forwarded(shelf):
    shelf.set_entries([_entry("a")])
    got = {}
    shelf.card_clicked.connect(lambda i: got.setdefault("click", i))
    shelf.star_clicked.connect(lambda i: got.setdefault("star", i))
    shelf.edit_clicked.connect(lambda i: got.setdefault("edit", i))
    shelf.gear_clicked.connect(lambda i: got.setdefault("gear", i))
    card = shelf.card_for("a")
    card.clicked.emit("a")
    card.star_clicked.emit("a")
    card.edit_clicked.emit("a")
    card.gear_clicked.emit("a")
    assert got == {"click": "a", "star": "a", "edit": "a", "gear": "a"}


def test_card_action_signals_are_forwarded(shelf):
    shelf.set_entries([_entry("a")])
    got = []
    shelf.launch_clicked.connect(lambda i: got.append(("launch", i)))
    shelf.cancel_clicked.connect(lambda i: got.append(("cancel", i)))
    shelf.quit_clicked.connect(lambda i: got.append(("quit", i)))
    shelf.enter_2fa_clicked.connect(lambda i: got.append(("2fa", i)))
    shelf.retry_clicked.connect(lambda i: got.append(("retry", i)))
    card = shelf.card_for("a")
    card.launch_clicked.emit("a")
    card.cancel_clicked.emit("a")
    card.quit_clicked.emit("a")
    card.enter_2fa_clicked.emit("a")
    card.retry_clicked.emit("a")
    assert got == [("launch", "a"), ("cancel", "a"), ("quit", "a"),
                   ("2fa", "a"), ("retry", "a")]


def test_set_state_routes_to_the_matching_card(shelf):
    shelf.set_entries([_entry("a")])
    shelf.set_state("a", "queued", "position 42", "raw queue detail")
    card = shelf.card_for("a")
    assert card.state() == "queued"
    assert card.footer_text() == "In queue · position 42"
    assert card.raw_error() == "raw queue detail"
    shelf.set_state("ghost", "failed", "boom", "traceback")


def test_shake_on_an_unknown_id_is_harmless(shelf):
    shelf.set_entries([_entry("a")])
    assert shelf.shake("ghost") is False


def test_shake_runs_on_a_real_card(shelf, monkeypatch):
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    shelf.set_entries([_entry("a")])
    assert shelf.shake("a") is True


def test_reduced_motion_skips_the_shake(shelf, monkeypatch):
    """The cap refusal still happens; it just does not animate."""
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    shelf.set_entries([_entry("a")])
    assert shelf.shake("a") is False


def test_head_row_is_the_fixed_height_the_handoff_gives_it(shelf):
    """Handoff §4.1c: head row `flex: 0 0 34px`. The shelf is the only band
    that stretches inside a 688px content area, so this height is load-bearing
    — a taller head row pushes 216px cards into a scrollbar."""
    assert shelf.head.height() == HEAD_H == 34


def test_edge_fades_only_appear_when_there_is_something_to_scroll(shelf):
    """Handoff §4.1c: the 36px masks fade in 'when content is off-screen
    either side'. One card in an 852px shelf has nowhere to scroll."""
    shelf.set_entries([_entry("a")])
    shelf.show()
    qapp = QApplication.instance()
    qapp.processEvents()
    assert shelf.fade_sides() == ()
    shelf.set_entries([_entry(str(i)) for i in range(12)])
    qapp.processEvents()
    assert "right" in shelf.fade_sides()


def test_the_right_edge_fade_actually_covers_the_cards(shelf, qapp):
    """fade_sides() only reports the decision. This proves the mask is drawn
    ABOVE the strip — with the overlay removed the edge pixel is a card, and
    this test fails."""
    shelf.set_entries([_entry(str(i)) for i in range(12)])
    shelf.show()
    qapp.processEvents()
    assert "right" in shelf.fade_sides()

    pm = QPixmap(shelf.size())
    pm.fill(Qt.black)
    shelf.render(pm)
    img = pm.toImage()

    def distance(a, b):
        return (abs(a.red() - b.red()) + abs(a.green() - b.green())
                + abs(a.blue() - b.blue()))

    area = shelf.scroll.geometry()
    edge = img.pixelColor(area.right() - 2, area.center().y())
    panel_bg = gp.panel(True)["bg"]
    accent = QColor("#4a8fe7")          # the card colour the mask must hide

    # The last pixel is ~94% along the gradient (fillRect covers [x, x+w-1]
    # while colorAt(1.0) lands on width()), so it is near-panel, never exact.
    assert distance(edge, panel_bg) < 40
    assert distance(edge, accent) > 150
