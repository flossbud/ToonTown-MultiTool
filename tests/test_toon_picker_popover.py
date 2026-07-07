from utils.recent_toons import ToonRecord
from utils.widgets.toon_picker_popover import ToonPickerPopover


def _toons():
    return [ToonRecord("Moe", "ttr", "d1", laff=120, max_laff=137, species="HORSE", accent="#4a8fe7"),
            ToonRecord("Zed", "cc", "", laff=None, max_laff=None, species="CAT", accent="#e05252")]


def test_builds_one_row_per_toon(qapp):
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=True)
    assert len(p.rows) == 2


def test_ttr_row_shows_laff_cc_row_hides_it(qapp):
    p = ToonPickerPopover(_toons(), primary_name="Moe", is_dark=True)
    assert p.rows[0].laff_label.isVisibleTo(p) is True     # TTR Moe, laff=120
    assert p.rows[1].laff_label.isVisibleTo(p) is False    # CC Zed, laff=None


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
