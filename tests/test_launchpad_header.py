"""The launchpad header: sheet buttons, session status line, placement."""

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from utils.widgets.window_chrome_style import header_top_radius_qss
from utils.widgets.launchpad.header import (
    BUTTON_H, HEADER_H, LOGO_GAP, LOGO_HEIGHT, ROW_BOTTOM, ROW_LEFT, SHEET_ACCOUNTS, SHEET_BUTTONS,
    SHEET_KEYSETS, SHEET_SETTINGS, STATUS_RIGHT, STATUS_TOP, LaunchpadHeader,
    SheetButtonRow, next_open_sheet, session_status_text,
)


HEADER_BG = "#1a1a1a"


def _over(colour: str, alpha: float, background: str) -> QColor:
    """``colour`` at ``alpha`` painted over ``background``."""
    top, under = QColor(colour), QColor(background)
    return QColor(*(round(t * alpha + u * (1 - alpha)) for t, u in (
        (top.red(), under.red()), (top.green(), under.green()),
        (top.blue(), under.blue()))))


def test_pressing_the_lit_button_closes_and_another_swaps():
    assert next_open_sheet(None, SHEET_KEYSETS) == SHEET_KEYSETS
    assert next_open_sheet(SHEET_KEYSETS, SHEET_KEYSETS) is None
    assert next_open_sheet(SHEET_KEYSETS, SHEET_SETTINGS) == SHEET_SETTINGS


@pytest.mark.parametrize("count, running, text", [
    (0, True, ""), (-2, True, ""), (0, False, ""),
    (1, True, "1 toon"), (2, True, "2 toons"), (4, True, "4 toons"),
    (1, False, "1 toon \u00b7 stopped"), (3, False, "3 toons \u00b7 stopped"),
])
def test_session_status_text(count, running, text):
    assert session_status_text(count, running) == text


def test_the_three_buttons_in_order_with_their_identity_colours():
    assert [(name, label, colour) for name, label, colour, _glyph in SHEET_BUTTONS] == [
        ("accounts", "Accounts", "#0077ff"),
        ("keysets", "Keysets", "#DAA520"),
        ("settings", "Settings", "#3da343"),
    ]


def test_row_emits_the_pressed_buttons_name(qapp):
    row = SheetButtonRow()
    seen = []
    row.pressed.connect(seen.append)
    row.buttons[SHEET_SETTINGS].click()
    row.buttons[SHEET_ACCOUNTS].click()
    assert seen == [SHEET_SETTINGS, SHEET_ACCOUNTS]


def test_row_lights_exactly_the_open_sheet(qapp):
    row = SheetButtonRow()
    assert row.open_sheet() is None
    row.set_open(SHEET_KEYSETS)
    assert [b.is_open() for b in row.buttons.values()] == [False, True, False]
    row.set_open(SHEET_ACCOUNTS)
    assert [b.is_open() for b in row.buttons.values()] == [True, False, False]
    row.set_open("no-such-sheet")
    assert row.open_sheet() is None
    assert not any(b.is_open() for b in row.buttons.values())


def test_buttons_are_32_high_and_never_overlap(qapp):
    row = SheetButtonRow()
    for lit in (None, SHEET_ACCOUNTS, SHEET_KEYSETS, SHEET_SETTINGS):
        row.set_open(lit)
        buttons = list(row.buttons.values())
        assert all(b.height() == BUTTON_H for b in buttons)
        for left, right in zip(buttons, buttons[1:]):
            assert left.geometry().right() + 5 == right.geometry().left() - 1
        assert row.width() == buttons[-1].geometry().right() + 1


@pytest.fixture
def mounted(qapp):
    """The header where it lives: at the top of a parent, 880 wide."""
    parent = QWidget()
    parent.resize(880, 400)
    header = LaunchpadHeader(parent)
    header.setGeometry(0, 0, 880, HEADER_H)
    # Styled as the window styles it: the lit fill is 55% over this.
    header.setStyleSheet(header_top_radius_qss(HEADER_BG, None, 16))
    parent.show()
    qapp.processEvents()
    yield header
    parent.close()


def test_placement_follows_the_design(mounted):
    assert mounted.buttons.pos().x() == ROW_LEFT
    assert mounted.buttons.geometry().bottom() + 1 == HEADER_H - ROW_BOTTOM
    assert mounted.status.pos().y() == STATUS_TOP
    assert mounted.status.geometry().right() + 1 == 880 - STATUS_RIGHT
    assert (mounted.hint_btn.pos().x(), mounted.hint_btn.pos().y()) == (13, 13)
    logo = mounted.logo.geometry()
    assert abs(logo.center().x() - 440) <= 1
    assert not logo.intersects(mounted.buttons.geometry())
    assert not logo.intersects(mounted.status.geometry())


def test_status_stays_right_aligned_as_the_count_changes(mounted):
    mounted.set_toon_count(3)
    assert mounted.status.text() == "3 toons"
    assert mounted.status.isVisible()
    assert mounted.status.geometry().right() + 1 == 880 - STATUS_RIGHT
    mounted.set_running(False)
    assert mounted.status.text() == "3 toons \u00b7 stopped"
    assert mounted.status.geometry().right() + 1 == 880 - STATUS_RIGHT
    mounted.set_toon_count(0)
    assert mounted.status.text() == ""
    assert not mounted.status.isVisible()


@pytest.mark.parametrize("width", [820, 880, 1280])
def test_the_wordmark_stays_clear_of_the_buttons_at_every_width(mounted, width):
    """The lit button is bold and wider; the wordmark must clear the row in
    every state, and must not jump when a sheet opens."""
    mounted.setGeometry(0, 0, width, HEADER_H)
    at_rest = mounted.logo.geometry()
    assert abs(at_rest.center().x() - width // 2) <= 1
    for lit in (SHEET_ACCOUNTS, SHEET_KEYSETS, SHEET_SETTINGS, None):
        mounted.set_open_sheet(lit)
        assert mounted.logo.geometry() == at_rest
        gap = at_rest.left() - (mounted.buttons.geometry().right() + 1)
        assert gap >= LOGO_GAP - 1, (width, lit, gap)
    assert mounted.status.geometry().right() + 1 == width - STATUS_RIGHT
    assert not at_rest.intersects(mounted.status.geometry())


def test_the_wordmark_is_full_size_when_there_is_room(mounted):
    assert mounted.logo.height() == LOGO_HEIGHT
    mounted.setGeometry(0, 0, 820, HEADER_H)
    assert mounted.logo.height() < LOGO_HEIGHT           # shrunk to fit
    mounted.setGeometry(0, 0, 880, HEADER_H)
    assert mounted.logo.height() == LOGO_HEIGHT


def _has_colour_like(image, rect, target, tolerance=60):
    target = QColor(target)
    for x in range(rect.left(), rect.right(), 2):
        for y in range(rect.top(), rect.bottom(), 2):
            c = image.pixelColor(x, y)
            if (abs(c.red() - target.red()) + abs(c.green() - target.green())
                    + abs(c.blue() - target.blue())) <= tolerance and c.alpha() > 200:
                return True
    return False


def test_the_lit_button_paints_its_identity_colour_mounted_in_the_header(mounted, qapp):
    """Rendered in place: a button's own glyph carries its colour at rest,
    and only the lit one is filled with it."""
    keysets = mounted.buttons.buttons[SHEET_KEYSETS]
    rect = keysets.geometry().translated(mounted.buttons.pos())
    label_area = rect.adjusted(34, 4, -6, -4)       # right of the glyph

    lit_fill = _over("#DAA520", 0.55, HEADER_BG)

    def fill_is_gold():
        image = mounted.grab().toImage()
        return _has_colour_like(image, label_area, lit_fill, tolerance=24)

    assert not fill_is_gold()
    mounted.set_open_sheet(SHEET_KEYSETS)
    qapp.processEvents()
    assert fill_is_gold()
    mounted.set_open_sheet(None)
    qapp.processEvents()
    assert not fill_is_gold()


def test_hint_button_reports_its_state_and_emits(mounted):
    seen = []
    mounted.hints_toggled.connect(lambda: seen.append(1))
    mounted.hint_btn.click()
    assert seen == [1]
    mounted.set_hints_enabled(False)
    assert "off" in mounted.hint_btn.toolTip()
    mounted.set_hints_enabled(True)
    assert "on" in mounted.hint_btn.toolTip()
    assert mounted.hint_btn.property("_always_tooltip") is True


def test_theme_switch_keeps_everything_placed(mounted):
    before = (mounted.buttons.geometry(), mounted.status.geometry())
    mounted.apply_theme(False, QColor("#333333"))
    assert (mounted.buttons.geometry(), mounted.status.geometry()) == before
    assert mounted.logo.pixmap() is not None and not mounted.logo.pixmap().isNull()
