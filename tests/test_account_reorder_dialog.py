import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.account_reorder_dialog import AccountReorderDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _accts(n, labels=None):
    out = []
    for i in range(n):
        lbl = "" if labels is None else labels[i]
        out.append({"id": f"id{i}", "label": lbl, "username": f"user{i}"})
    return out


def test_ordered_ids_starts_in_given_order(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    assert d.ordered_ids() == ["id0", "id1", "id2"]


def test_move_down_then_up(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    d._move_down(0)
    assert d.ordered_ids() == ["id1", "id0", "id2"]
    d._move_up(2)
    assert d.ordered_ids() == ["id1", "id2", "id0"]


def test_move_clamps_at_ends(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(2))
    d._move_up(0)      # already top -> no-op
    d._move_down(1)    # already bottom -> no-op
    assert d.ordered_ids() == ["id0", "id1"]


def test_rows_renumber_and_disable_ends(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    rows = d._rows  # top-to-bottom _ReorderRow widgets
    assert [r.badge.text() for r in rows] == ["1", "2", "3"]
    assert not rows[0].up_btn.isEnabled()       # first row: up disabled
    assert not rows[-1].down_btn.isEnabled()    # last row: down disabled
    assert rows[0].down_btn.isEnabled() and rows[1].up_btn.isEnabled()
    d._move_down(0)
    rows = d._rows
    assert [r.badge.text() for r in rows] == ["1", "2", "3"]  # renumbered after move


def test_row_text_is_label_or_username(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(2, labels=["Main", ""]))
    rows = d._rows
    assert rows[0].title.text() == "Main"      # has label -> label primary
    assert "user0" in rows[0].subtitle.text()  # username shown dim when label set
    assert rows[1].title.text() == "user1"     # no label -> username primary
    assert rows[1].subtitle.text() == ""       # no dim username when none/no label


def test_arrow_button_moves_row(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    d._rows[0].down_btn.click()
    assert d.ordered_ids() == ["id1", "id0", "id2"]


def test_cc_game_title_and_accent(qapp):
    d = AccountReorderDialog(game="cc", accounts=_accts(2))
    assert "Corporate Clash" in d.windowTitle()
    assert "Corporate Clash" in d.title_label.text()
    # CC accent badge color present in a row's stylesheet.
    assert "#F26D21" in d._rows[0].badge.styleSheet()


def test_modal_tall_enough_for_multiple_rows(qapp):
    # Regression: the modal must open tall enough to list several accounts, not
    # collapse to a single row. The scroll area reserves height for >=3 rows.
    d = AccountReorderDialog(game="ttr", accounts=_accts(5))
    assert d._scroll.minimumHeight() >= 3 * 50  # at least ~3 rows visible


def test_modal_height_caps_for_many_accounts(qapp):
    # With many accounts it caps (then scrolls) rather than growing unbounded.
    small = AccountReorderDialog(game="ttr", accounts=_accts(3))
    big = AccountReorderDialog(game="ttr", accounts=_accts(16))
    # 16-account modal is not taller than a 6-row cap (capped), and is >= the 3-row one
    assert big._scroll.minimumHeight() >= small._scroll.minimumHeight()
    assert big._scroll.minimumHeight() <= 6 * 60 + 16
