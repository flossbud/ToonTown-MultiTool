import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_constructs_with_active_game(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    assert rail._active == "ttr"


def test_has_two_icon_chips(qapp):
    from tabs.keymap_tab import _GameSubRail
    from utils.widgets.chip_button import ChipButton
    rail = _GameSubRail(active_game="ttr")
    chips = rail.findChildren(ChipButton)
    assert len(chips) == 2
    # Order: TTR then CC.
    assert rail._buttons["ttr"] is chips[0]
    assert rail._buttons["cc"] is chips[1]


def test_chips_are_icon_only(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    for game, btn in rail._buttons.items():
        assert btn.toolButtonStyle() == Qt.ToolButtonIconOnly, (
            f"{game} chip is not icon-only"
        )
        # 56x40 fixed size per spec (matches the prior _SegmentedSwitch footprint).
        assert btn.minimumSize().width() == 56
        assert btn.minimumSize().height() == 40


def test_has_pill_indicator(qapp):
    from tabs.keymap_tab import _GameSubRail
    from utils.widgets.pill_indicator import PillIndicator
    rail = _GameSubRail(active_game="ttr")
    pills = rail.findChildren(PillIndicator)
    assert len(pills) == 1


def test_emits_game_changed_on_click(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    fired = []
    rail.game_changed.connect(fired.append)
    rail._buttons["cc"].click()
    assert fired == ["cc"]


def test_clicking_active_chip_does_not_re_emit(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    fired = []
    rail.game_changed.connect(fired.append)
    rail._buttons["ttr"].click()
    assert fired == []
