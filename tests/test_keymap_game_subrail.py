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


def test_set_active_updates_internal(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    rail.set_active("cc")
    assert rail._active == "cc"
    assert rail._buttons["cc"].isChecked()
    assert not rail._buttons["ttr"].isChecked()


def test_set_active_is_idempotent(qapp):
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    fired = []
    rail.game_changed.connect(fired.append)
    rail.set_active("ttr")
    assert fired == []


def test_pill_color_matches_active_game(qapp):
    from tabs.keymap_tab import _GameSubRail
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)

    rail = _GameSubRail(active_game="ttr")
    assert rail._pill._border_color.name().lower() == c["game_pill_ttr"].lower()

    rail.set_active("cc")
    assert rail._pill._border_color.name().lower() == c["game_pill_cc"].lower()


def test_chips_have_transparent_background(qapp):
    """Without transparent chip backgrounds, the lowered PillIndicator is
    hidden behind the opaque system-style fill, defeating the slide animation."""
    from tabs.keymap_tab import _GameSubRail
    rail = _GameSubRail(active_game="ttr")
    for game, btn in rail._buttons.items():
        qss = btn.styleSheet()
        assert "background: transparent" in qss, (
            f"{game} chip has no transparent-bg QSS; pill is hidden"
        )


def test_keymap_tab_uses_game_sub_rail_when_both_detected(qapp, monkeypatch):
    from tabs.keymap_tab import KeymapTab, _GameSubRail
    from utils.keymap_manager import KeymapManager

    class _FakeSettings:
        def __init__(self):
            self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        def get(self, k, default=None):
            return self._d.get(k, default)
        def set(self, k, v):
            self._d[k] = v
        def on_change(self, cb):
            pass

    # Force both-games-detected so the sub-rail is built.
    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: True)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: True)

    tab = KeymapTab(KeymapManager(), settings_manager=_FakeSettings())
    assert isinstance(tab._segmented, _GameSubRail), (
        f"expected _GameSubRail, got {type(tab._segmented).__name__}"
    )
