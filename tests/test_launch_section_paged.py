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
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=6)
    assert len(sec.tiles) == 2
    # The slot number moved onto the portrait slot (was a standalone `badge`).
    assert sec.tiles[0].portrait._slot == 5
    assert sec.tiles[1].portrait._slot == 6


def test_set_page_renders_account_count_subline(qapp):
    # Regression: the production render path is set_page (LaunchTab uses it, NOT
    # the set_accounts shim). set_page must restate the whole-section count on
    # the card sub-line so a populated section never keeps the seeded
    # "No accounts yet". Drives the SAME path production uses.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    page1 = [_acct(1, "id1"), _acct(2, "id2"), _acct(3, "id3"), _acct(4, "id4")]
    sec.set_page(page1, page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=4)
    assert "4" in sec.subline.text()
    assert "No accounts" not in sec.subline.text()


def test_set_page_shows_total_across_pages_not_page_slice(qapp):
    # The sub-line reflects the WHOLE section (total_count), not just this
    # page's slice: page 2 of a 6-account section still reads "6 accounts".
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    page2 = [_acct(5, "id5"), _acct(6, "id6")]
    sec.set_page(page2, page=1, page_count=2, base_index=4,
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=6)
    assert "6" in sec.subline.text()


def test_set_page_empty_section_reads_no_accounts(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([], page=0, page_count=1, base_index=0, activity=[False],
                 show_empty_state=True, at_ceiling=False, total_count=0)
    assert "No accounts" in sec.subline.text()


def test_tile_signals_carry_account_id(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "abc")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
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
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
    seen = []
    getattr(sec, section_sig).connect(seen.append)
    getattr(sec.tiles[0], tile_sig).emit()
    assert seen == ["xyz"]


def test_set_activity_preserves_add_button_intent_before_show(qapp):
    # set_activity must not hide Add just because the section isn't shown yet
    # (add_btn.isVisible() is False pre-show); it uses the stored show_add intent.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
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
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=6)
    assert len(sec.tiles) == 4


def test_zero_accounts_shows_empty_state_and_hides_pager(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([], page=0, page_count=1, base_index=0, activity=[False],
                 show_empty_state=True, at_ceiling=False, total_count=0)
    sec.show()
    assert sec.empty_state.isVisible()
    assert not sec.pager.isVisible()


def test_reserved_empty_page_shows_hint_not_empty_state(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([], page=1, page_count=2, base_index=4, activity=[False, False],
                 show_empty_state=False, at_ceiling=False, total_count=4)
    sec.show()
    assert not sec.empty_state.isVisible()
    assert sec.pager.isVisible()
    assert sec.empty_page_hint.isVisible()


def test_at_ceiling_hides_add_button(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    full = [_acct(13, f"id{13+i}") for i in range(4)]
    sec.set_page(full, page=3, page_count=4, base_index=12,
                 activity=[False] * 4, show_empty_state=False, at_ceiling=True,
                 total_count=16)
    sec.show()
    assert not sec.pager.add_btn.isVisible()


def test_page_changed_emitted_by_pager(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
    seen = []
    sec.page_changed.connect(seen.append)
    sec.pager.next_btn.click()
    assert seen == [1]


def test_compact_height_stable_one_vs_four_tiles(qapp):
    # Reserved 2-row grid: a 1-tile page must not be shorter than a 4-tile page.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
    one = sec.grid_container.minimumHeight()
    four = [_acct(i, f"id{i}") for i in range(4)]
    sec.set_page(four, page=0, page_count=2, base_index=0,
                 activity=[False, False], show_empty_state=False, at_ceiling=False,
                 total_count=4)
    assert sec.grid_container.minimumHeight() == one  # reserved, not content-driven
    assert one >= 2 * 130  # at least two tile rows


def test_grid_columns_do_not_stretch(qapp):
    # Tiles are a fixed 336px width now, so the grid columns must NOT stretch
    # (a stretched column would strand the fixed tile in an over-wide cell).
    # The 2-column block is centered horizontally via outer stretch instead.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    assert sec.grid.columnStretch(0) == 0
    assert sec.grid.columnStretch(1) == 0


def test_single_tile_occupies_one_quadrant_not_full_row(qapp):
    # A page with one account: the fixed-width tile must stay 336px (one
    # quadrant), never stretch across the whole row.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
    sec.resize(520, 460)
    sec.show()
    QApplication.processEvents()
    tile = sec.tiles[0]
    assert tile.width() == 336, tile.width()


def test_section_reexposes_reorder_and_threads_show_reorder(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    seen = []
    sec.reorder_clicked.connect(lambda: seen.append("x"))
    sec.set_page([_acct(1, "a"), _acct(2, "b")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=2, show_reorder=True)
    sec.show()
    assert sec.pager.reorder_btn.isVisible()
    sec.pager.reorder_btn.click()
    assert seen == ["x"]
    sec.set_page([_acct(1, "a")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=1)
    assert not sec.pager.reorder_btn.isVisible()


def test_set_activity_preserves_reorder_chip_intent(qapp):
    # A dot-only refresh (set_activity) must not hide the reorder chip when it
    # was shown by the prior set_page (parity with the add-button intent).
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_page([_acct(1, "a"), _acct(2, "b")], page=0, page_count=1, base_index=0,
                 activity=[False], show_empty_state=False, at_ceiling=False,
                 total_count=2, show_reorder=True)
    sec.set_activity([True])
    sec.show()
    assert sec.pager.reorder_btn.isVisible()
