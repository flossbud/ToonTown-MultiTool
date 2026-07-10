import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def card(qapp):
    from utils.widgets.logs_console.logs_card import LogsCard
    c = LogsCard()
    c.append("[Credentials] line")
    c.resize(868, 640)
    c.show()
    QApplication.processEvents()
    return c


def test_light_theme_flips_console_and_ink(card):
    card.apply_theme(False)
    assert card.pane._t["console_bg"] == "#f1f5f9"
    assert card.pane.delegate._t["levels"]["error"] == "#b91c1c"
    assert "f1f5f9" not in card.search.styleSheet()       # search never leaks console_bg
    assert "#8749E0" in card.search.styleSheet()          # light focus ring = base c


def test_dark_theme_restores(card):
    card.apply_theme(True)
    assert card.pane._t["console_bg"] == "#101413"
    assert card.pane.delegate._t["levels"]["error"] == "#ea7a7a"
    assert "#a87cf0" in card.search.styleSheet()          # dark focus ring = bright b


def test_chips_restyle_with_theme(card):
    QApplication.processEvents()
    chip = card.chips()[0]
    card.apply_theme(False)
    assert "#0f766e" in chip.styleSheet()                 # light Credentials ink
    card.apply_theme(True)
    assert "#4dd2c3" in chip.styleSheet()                 # dark Credentials ink


def test_toast_stays_dark_in_both_themes(card):
    for is_dark in (True, False):
        card.apply_theme(is_dark)
        assert "rgba(0, 0, 0, 184)" in card.pane.toast.styleSheet()  # alpha(#000,0.72)
    card.apply_theme(True)


def test_theme_roundtrip_with_full_content(card):
    """Busy-card roundtrip: chips + filters + paused pill + toast all alive."""
    for i in range(60):
        card.append(f"[Service] line {i}")
        card.append(f"[TTR API] line {i}")
    QApplication.processEvents()
    card.search.setText("line")
    # "[Service]" has 60 pre-existing matches for "line" — enough rows that
    # the filtered view still overflows the pane after pausing. "[Credentials]"
    # (chips()[0]) has only the fixture's single line: filtering narrows the
    # proxy to 0-1 rows, the console has nothing left to scroll past, and
    # set_following(True) legitimately auto-re-engages on the next
    # valueChanged — that's correct follow-FSM behavior, not a bug, but it
    # means a pending line could never survive to be asserted on below.
    chip = next(c for c in card.chips() if c.text() == "[Service]")
    chip.setChecked(True)
    QApplication.processEvents()   # let the filtered relayout settle before pausing
    # Precondition for the pending assertion below: the filtered view must
    # genuinely overflow, or the follow FSM self-heals and this test's premise
    # (not its subject) is what broke.
    from utils.widgets.logs_console.pane import FOLLOW_SLOP
    assert card.pane.view.verticalScrollBar().maximum() > FOLLOW_SLOP
    card.pane.set_following(False)
    # Match the active tag + query filters (chip's tag, "line" in the
    # message) so the append actually lands in the proxy as a pending row —
    # a line that the current filter would exclude can never become pending.
    card.append(f"{chip.text()} another pending line while paused")
    QApplication.processEvents()
    card.pane.show_toast("busy")
    card.apply_theme(False)
    card.apply_theme(True)
    # State survived the flips:
    assert card.pane.pending_count() >= 1
    assert chip.isChecked()
    assert card.search.text() == "line"
    card.search.setText("")
    chip.setChecked(False)
    card.pane.set_following(True)
