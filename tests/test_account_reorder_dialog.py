import pytest
from PySide6.QtCore import QPoint
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



def test_drag_moves_account_to_target(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(4))  # id0..id3
    d._begin_drag(0, d.mapToGlobal(QPoint(0, 0)))
    assert d._dragging is True
    d._drag_to(2)
    d._end_drag()
    assert d.ordered_ids() == ["id1", "id2", "id0", "id3"]
    assert d._dragging is False


def test_drag_to_clamps_to_last(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    d._begin_drag(1, d.mapToGlobal(QPoint(0, 0)))
    d._drag_to(99)        # clamps to last slot
    d._end_drag()
    assert d.ordered_ids() == ["id0", "id2", "id1"]


def test_drag_cancel_restores_order(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    before = d.ordered_ids()
    d._begin_drag(0, d.mapToGlobal(QPoint(0, 0)))
    d._drag_to(2)
    d._cancel_drag()
    assert d.ordered_ids() == before
    assert d._dragging is False


def test_begin_drag_makes_ghost_and_hides_row_then_end_cleans_up(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    row = d._rows[0]
    d._begin_drag(0, d.mapToGlobal(QPoint(0, 0)))
    assert d._ghost is not None
    assert row.isHidden()
    assert d._placeholder is not None
    d._end_drag()
    assert d._ghost is None
    assert d._placeholder is None
    assert d._dragging is False


def test_no_qdrag_plumbing_remains(qapp):
    import utils.widgets.account_reorder_dialog as m
    from utils.widgets.account_reorder_dialog import _ReorderRow
    assert not hasattr(m, "_MIME")
    # Verify no custom overrides remain (inherited Qt base methods are expected).
    assert "dropEvent" not in _ReorderRow.__dict__
    assert "dragEnterEvent" not in _ReorderRow.__dict__


def test_drag_to_same_target_is_noop(qapp):
    d = AccountReorderDialog(game="ttr", accounts=_accts(3))
    d._begin_drag(1, d.mapToGlobal(QPoint(0, 0)))
    d._drag_to(1)
    d._end_drag()
    assert d.ordered_ids() == ["id0", "id1", "id2"]


def test_target_index_for_y_maps_and_clamps(qapp):
    # Coordinate->slot math: above-all -> 0, just past the first remaining row's
    # midpoint -> 1, below-all -> len(others). Derived from real geometry so it
    # catches a midpoint-math regression (e.g. height/2 -> height).
    d = AccountReorderDialog(game="ttr", accounts=_accts(4))
    d.resize(460, 460)
    d.show()
    QApplication.processEvents()
    d._begin_drag(0, d.mapToGlobal(QPoint(0, 0)))  # row 0 dragged -> others = rows 1,2,3
    others = [r for r in d._rows if r is not d._dragged_row]
    assert d._target_index_for_y(-50) == 0                       # above everything
    assert d._target_index_for_y(10_000) == len(others)          # below everything
    just_past_first = int(others[0].y() + others[0].height() / 2 + 1)
    assert d._target_index_for_y(just_past_first) == 1           # past 1st other's midpoint
    d._cancel_drag()
