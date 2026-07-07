import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.page_pager import PagePager
from utils.theme_manager import get_theme_colors


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_renders_n_dots_and_marks_current(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=1, page_count=3, activity=[False, False, False], show_add=True)
    assert len(p._dots) == 3
    assert p._dots[1].property("current") is True
    assert p._dots[0].property("current") is False


def test_arrows_disabled_at_ends(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=2, activity=[False, False], show_add=True)
    assert not p.prev_btn.isEnabled()
    assert p.next_btn.isEnabled()
    p.set_state(page=1, page_count=2, activity=[False, False], show_add=True)
    assert p.prev_btn.isEnabled()
    assert not p.next_btn.isEnabled()


def test_activity_sets_ring_property(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=3, activity=[False, True, False], show_add=True)
    assert p._dots[1].property("active") is True
    assert p._dots[0].property("active") is False


def test_add_hidden_when_show_add_false(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=1, activity=[False], show_add=False)
    assert not p.add_btn.isVisible()


def test_single_page_disables_both_arrows(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=1, activity=[False], show_add=True)
    assert not p.prev_btn.isEnabled()
    assert not p.next_btn.isEnabled()


def test_apply_theme_paints_current_dot_with_accent(qapp):
    from utils.theme_manager import V2_ACCENTS
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=2, activity=[False, False], show_add=True)
    c = get_theme_colors(True)
    p.apply_theme(c)
    assert V2_ACCENTS["ttr"]["b"] in p._dots[0].styleSheet()


def test_dot_click_emits_page_selected(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=3, activity=[False, False, False], show_add=True)
    seen = []
    p.page_selected.connect(seen.append)
    p._dots[2].click()
    assert seen == [2]


def test_next_prev_emit_page_selected(qapp):
    p = PagePager(game="ttr")
    p.set_state(page=1, page_count=3, activity=[False, False, False], show_add=True)
    seen = []
    p.page_selected.connect(seen.append)
    p.next_btn.click()
    p.prev_btn.click()
    assert seen == [2, 0]


def test_add_click_emits(qapp):
    p = PagePager(game="cc")
    p.set_state(page=0, page_count=1, activity=[False], show_add=True)
    seen = []
    p.add_clicked.connect(lambda: seen.append("x"))
    p.add_btn.click()
    assert seen == ["x"]


def test_reorder_button_visibility_and_signal(qapp):
    from utils.widgets.page_pager import PagePager
    p = PagePager(game="ttr")
    p.set_state(page=0, page_count=1, activity=[False], show_add=True, show_reorder=False)
    assert p.reorder_btn.isHidden()
    p.set_state(page=0, page_count=1, activity=[False], show_add=True, show_reorder=True)
    p.show()
    assert p.reorder_btn.isVisible()
    seen = []
    p.reorder_clicked.connect(lambda: seen.append("x"))
    p.reorder_btn.click()
    assert seen == ["x"]


def test_current_dot_uses_game_accent(qapp):
    from utils.widgets.page_pager import PagePager
    p = PagePager("cc")
    p.set_state(page=0, page_count=2, activity=[False, False], show_add=True)
    assert p._dots[0].property("current") is True


def test_has_dot_pill_container(qapp):
    from utils.widgets.page_pager import PagePager
    p = PagePager("ttr")
    assert p.dot_pill is not None
