from utils.recent_toons import ToonRecord
from utils.widgets.toon_picker_popover import ToonPickerPopover


def _toons():
    return [ToonRecord("Moe", "ttr", "d1", laff=120, max_laff=137, species="HORSE", accent="#4a8fe7"),
            ToonRecord("Zed", "cc", "", laff=None, max_laff=None, species="CAT", accent="#e05252")]


def test_builds_one_row_per_toon(qapp):
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=True)
    assert len(p.rows) == 2


def test_rows_do_not_show_laff(qapp):
    # laff was removed from the picker per product feedback.
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=True)
    assert not hasattr(p.rows[0], "laff_label")


def test_click_emits_picked(qapp):
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=True)
    got = []
    p.picked.connect(got.append)
    p.rows[1]._emit_click()
    assert got == ["Zed"]


def test_empty_list_builds(qapp):
    p = ToonPickerPopover([], primary_name=None, is_dark=True)
    assert p.rows == []


def test_paints_without_error(qapp):
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=False)
    p.grab()
