import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.launch_section import LaunchSection


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _acct(i, aid):
    return {"label": f"A{i}", "username": f"u{i}", "id": aid, "state": "idle",
            "message": "", "raw_error": ""}


def test_set_page_renders_slice_with_absolute_badges(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    page2 = [_acct(5, "id5"), _acct(6, "id6")]
    sec.set_page(page2, page=1, page_count=2, base_index=4,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    assert len(sec.tiles) == 2
    assert sec.tiles[0].badge.text() == "5"
    assert sec.tiles[1].badge.text() == "6"


def test_tile_signals_carry_account_id(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "abc")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False)
    seen = []
    sec.tile_launch.connect(seen.append)
    sec.tiles[0].launch_clicked.emit()
    assert seen == ["abc"]


@pytest.mark.parametrize("tile_sig,section_sig", [
    ("launch_clicked", "tile_launch"),
    ("quit_clicked", "tile_quit"),
    ("cancel_clicked", "tile_cancel"),
    ("retry_clicked", "tile_retry"),
    ("enter_2fa_clicked", "tile_enter_2fa"),
    ("edit_clicked", "tile_edit"),
    ("delete_clicked", "tile_delete"),
    ("expand_error_clicked", "tile_expand_error"),
])
def test_all_eight_tile_signals_carry_account_id(qapp, tile_sig, section_sig):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "xyz")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False)
    seen = []
    getattr(sec, section_sig).connect(seen.append)
    getattr(sec.tiles[0], tile_sig).emit()
    assert seen == ["xyz"]


def test_set_activity_preserves_add_button_intent_before_show(qapp):
    # set_activity must not hide Add just because the section isn't shown yet
    # (add_btn.isVisible() is False pre-show); it uses the stored show_add intent.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    sec.set_activity([True, False])
    sec.show()
    assert sec.pager.add_btn.isVisible()  # still shown after a dot refresh


def test_empty_page_reservation_matches_grid_reservation(qapp):
    # A reserved (empty) landing page must reserve the SAME height the populated
    # grid does, so the section doesn't shrink when you flip to it.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    assert sec.empty_page_hint.minimumHeight() == sec.grid_container.minimumHeight()


def test_set_page_caps_at_four_tiles(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    over = [_acct(i, f"id{i}") for i in range(6)]
    sec.set_page(over, page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    assert len(sec.tiles) == 4


def test_zero_accounts_shows_empty_state_and_hides_pager(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([], page=0, page_count=1, base_index=0, activity=[False],
                 show_empty_state=True, at_ceiling=False)
    sec.show()
    assert sec.empty_state.isVisible()
    assert not sec.pager.isVisible()


def test_reserved_empty_page_shows_hint_not_empty_state(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([], page=1, page_count=2, base_index=4, activity=[False, False],
                 show_empty_state=False, at_ceiling=False)
    sec.show()
    assert not sec.empty_state.isVisible()
    assert sec.pager.isVisible()
    assert sec.empty_page_hint.isVisible()


def test_at_ceiling_hides_add_button(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    full = [_acct(13, f"id{13+i}") for i in range(4)]
    sec.set_page(full, page=3, page_count=4, base_index=12,
                 activity=[False] * 4, show_empty_state=False, at_ceiling=True)
    sec.show()
    assert not sec.pager.add_btn.isVisible()


def test_page_changed_emitted_by_pager(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    seen = []
    sec.page_changed.connect(seen.append)
    sec.pager.next_btn.click()
    assert seen == [1]


def test_compact_height_stable_one_vs_four_tiles(qapp):
    # Reserved 2-row grid: a 1-tile page must not be shorter than a 4-tile page.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    one = sec.grid_container.minimumHeight()
    four = [_acct(i, f"id{i}") for i in range(4)]
    sec.set_page(four, page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False)
    assert sec.grid_container.minimumHeight() == one  # reserved, not content-driven
    assert one >= 2 * 130  # at least two tile rows


def test_grid_is_uniform_2x2(qapp):
    # Both columns and both rows carry equal, positive stretch so every cell is
    # always 1/4 of the grid area (a lone tile cannot expand to fill the row).
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    assert sec.grid.columnStretch(0) == sec.grid.columnStretch(1) > 0
    assert sec.grid.rowStretch(0) == sec.grid.rowStretch(1) > 0


def test_single_tile_occupies_one_quadrant_not_full_row(qapp):
    # A page with one account: the tile must stay ~half width (top-left quadrant),
    # not stretch across the whole row.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False)
    sec.resize(520, 460)
    sec.show()
    QApplication.processEvents()
    tile = sec.tiles[0]
    grid_w = sec.grid_container.width()
    assert grid_w > 0
    # The tile sits in column 0 of a 2-column grid -> well under full width.
    assert tile.width() < grid_w * 0.6, (tile.width(), grid_w)


def test_section_reexposes_reorder_and_threads_show_reorder(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    seen = []
    sec.reorder_clicked.connect(lambda: seen.append("x"))
    sec.set_page([_acct(1, "a"), _acct(2, "b")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False, show_reorder=True)
    sec.show()
    assert sec.pager.reorder_btn.isVisible()
    sec.pager.reorder_btn.click()
    assert seen == ["x"]
    sec.set_page([_acct(1, "a")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False)
    assert not sec.pager.reorder_btn.isVisible()
