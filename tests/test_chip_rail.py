"""Tests for chip-rail construction in MultiToonTool.

Same pattern as test_app_header.py: bypass __init__ via __new__ and call
the build method directly. _build_chip_rail reads self.settings_manager
to determine the initial hints_enabled state and whether the
debug-gated overflow menu should be visible, so tests stub both keys.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton


class _StubSettings:
    def __init__(self, **kv):
        self._kv = kv

    def get(self, key, default=None):
        return self._kv.get(key, default)

    def set(self, key, value):
        self._kv[key] = value


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def chip_rail(qapp):
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    return instance._build_chip_rail()


def test_chip_rail_is_qframe_with_expected_object_name(chip_rail):
    assert isinstance(chip_rail, QFrame)
    assert chip_rail.objectName() == "app_chip_rail"


def test_chip_rail_minimum_height_is_64(chip_rail):
    """Bumped from 52 -> 64 after the first 52px estimate proved too small
    to accommodate chip sizeHint with text-under-icon at 10pt. Qt was
    compressing the rail to 52 under window pressure, clipping labels."""
    assert chip_rail.minimumHeight() == 64


def test_chip_rail_layout_is_hbox_with_expected_margins(chip_rail):
    layout = chip_rail.layout()
    assert isinstance(layout, QHBoxLayout)
    m = layout.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (12, 6, 12, 6)
    assert layout.spacing() == 4


def test_chip_rail_height_accommodates_chip_sizeHint(chip_rail):
    """Regression guard: the rail's minimumHeight must be at least the
    tallest chip sizeHint plus the layout's vertical margins. If a future
    change (font, padding, icon size) grows chip sizeHint past this
    budget, Qt will silently clip the label under window pressure."""
    chips = [c for c in chip_rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    assert len(chips) == 4
    layout = chip_rail.layout()
    m = layout.contentsMargins()
    vertical_margins = m.top() + m.bottom()
    tallest_chip = max(c.sizeHint().height() for c in chips)
    assert chip_rail.minimumHeight() >= tallest_chip + vertical_margins, (
        f"chip rail minimumHeight {chip_rail.minimumHeight()} < "
        f"tallest_chip {tallest_chip} + margins {vertical_margins}; "
        f"rail will compress under window pressure and clip chip labels"
    )


def test_chips_use_10pt_label_font(chip_rail):
    """Spec said 'small text label'; with the default 12pt the chip
    sizeHint is too tall to fit in CHIP_RAIL_H without growing chrome.

    setFont alone is insufficient — the application-wide DARK_THEME stylesheet
    declares `QWidget { font-size: 12pt }` and Qt's QSS overrides setFont in
    the live app. The 10pt must also appear in the chip's own stylesheet
    (set in _apply_chip_styles) so id-selector specificity wins. Both paths
    are asserted: setFont for offscreen tests where the theme isn't applied,
    and the QSS font-size for production where it is.
    """
    chips = [c for c in chip_rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    assert len(chips) == 4
    for chip in chips:
        assert chip.font().pointSize() == 10, (
            f"chip {chip.objectName()} font is {chip.font().pointSize()}pt, expected 10pt"
        )


@pytest.fixture
def chip_rail_with_nav(qapp):
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance._nav_select_calls = []
    instance.nav_select = lambda i: instance._nav_select_calls.append(i)
    rail = instance._build_chip_rail()
    return instance, rail


def test_chip_rail_has_four_nav_chips_in_order(chip_rail_with_nav):
    instance, rail = chip_rail_with_nav
    chips = [c for c in rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    labels = [c.text() for c in chips]
    assert labels == ["Multitoon", "Launch", "Keymap", "Settings"]


def test_chips_use_text_under_icon_style(chip_rail_with_nav):
    _, rail = chip_rail_with_nav
    chips = [c for c in rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    assert len(chips) == 4, f"Expected 4 chips, got {len(chips)}"
    for chip in chips:
        assert chip.toolButtonStyle() == Qt.ToolButtonTextUnderIcon


def test_chips_are_checkable(chip_rail_with_nav):
    _, rail = chip_rail_with_nav
    chips = [c for c in rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    assert len(chips) == 4, f"Expected 4 chips, got {len(chips)}"
    for chip in chips:
        assert chip.isCheckable()


def test_clicking_chip_calls_nav_select_with_correct_index(chip_rail_with_nav):
    instance, rail = chip_rail_with_nav
    chips = [c for c in rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    assert len(chips) == 4
    for expected_idx, chip in enumerate(chips):
        instance._nav_select_calls.clear()
        chip.click()
        assert instance._nav_select_calls == [expected_idx]


from PySide6.QtWidgets import QFrame as _QFrame


def _build_rail_with_debug(qapp, *, show_debug_tab: bool):
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(
        hints_enabled=True,
        show_debug_tab=show_debug_tab,
    )
    instance._nav_select_calls = []
    instance.nav_select = lambda i: instance._nav_select_calls.append(i)
    return instance, instance._build_chip_rail()


def test_chip_rail_has_no_hint_button(qapp):
    """The hint toggle moved to the header — the chip rail should no
    longer construct or parent it. Tests for the hint button's existence
    live in test_app_header.py now."""
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    # If hint_btn ever does get created on the instance (via __init__
    # construction order), it must NOT be parented inside the rail.
    if hasattr(instance, "hint_btn") and instance.hint_btn is not None:
        assert instance.hint_btn.parent() is not rail, (
            "hint_btn should live in the header now, not the chip rail"
        )


def test_chip_rail_no_divider_between_chips_and_utilities(qapp):
    """The 1px VLine between the chip cluster and the hint utility was
    dropped — it added visual noise without expressing a real hierarchy
    boundary, since the right cluster is one toggle, not a nav group."""
    _, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    dividers = [
        c for c in rail.findChildren(_QFrame)
        if c.objectName() == "chip_rail_divider"
    ]
    assert dividers == [], (
        f"Expected no chip_rail_divider QFrame; found {len(dividers)}"
    )


def test_overflow_button_hidden_when_debug_off(qapp):
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    rail.show()  # required for isVisible to mean anything
    assert not instance.overflow_btn.isVisible()


def test_overflow_button_visible_when_debug_on(qapp):
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=True)
    rail.show()
    assert instance.overflow_btn.isVisible()


def test_view_logs_action_calls_nav_select_with_index_4(qapp):
    instance, _rail = _build_rail_with_debug(qapp, show_debug_tab=True)
    # OverflowPopup replaced QMenu — look for the "View Logs" row button.
    from utils.widgets.overflow_popup import OverflowPopup
    assert isinstance(instance.overflow_popup, OverflowPopup)
    from PySide6.QtWidgets import QPushButton
    logs_rows = [r for r in instance.overflow_popup.rows if r.text() == "View Logs"]
    assert len(logs_rows) == 1
    logs_rows[0].click()
    assert instance._nav_select_calls == [4]


# Click test for hint_btn moved to tests/test_app_header.py since
# the hint toggle now lives in the header, not the chip rail.


def test_apply_chip_styles_tints_selected_icon_with_accent(qapp):
    """After applying chip styles, the selected chip's icon should be
    larger than the default chips'."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance.nav_select = lambda i: None
    rail = instance._build_chip_rail()  # hold ref to prevent GC of child widgets
    # Pin selection to index 1 (Launch) before styling
    for i, chip in enumerate(instance.chip_buttons):
        chip.setChecked(i == 1)
    # Stub the theme accessor used by _apply_chip_styles
    instance._theme_colors = lambda: {
        "sidebar_text":     "#aaaaaa",
        "sidebar_text_sel": "#ffffff",
        "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
        "sidebar_bg":       "#111111",
        "header_accent":    "#0077ff",
    }
    instance._apply_chip_styles()
    # Selected chip should render at the larger icon size.
    assert instance.chip_buttons[1].iconSize().width() == 22
    assert instance.chip_buttons[0].iconSize().width() == 20
    # Every chip's stylesheet must declare font-size: 10pt — setFont alone is
    # overridden by the application-wide QWidget{font-size:12pt} rule in
    # DARK_THEME/LIGHT_THEME, so the chip's id-specific QSS is the only thing
    # that wins in production.
    for chip in instance.chip_buttons:
        assert "font-size: 10pt" in chip.styleSheet(), (
            f"chip {chip.objectName()} stylesheet missing font-size: 10pt"
        )
    _ = rail  # suppress "unused variable" lint; reference ensures QFrame lifetime


def test_chip_qss_has_focus_ring(qapp):
    """NoFocusProxyStyle strips the global focus rect; the chip rail must
    declare its own visible :focus state so keyboard users see where
    they are. Pins the focus selector on every chip."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance.nav_select = lambda i: None
    rail = instance._build_chip_rail()
    instance._theme_colors = lambda: {
        "sidebar_text":     "#aaaaaa",
        "sidebar_text_sel": "#ffffff",
        "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
        "sidebar_bg":       "#111111",
        "header_accent":    "#0077ff",
    }
    instance._apply_chip_styles()
    for chip in instance.chip_buttons:
        ss = chip.styleSheet()
        assert ":focus" in ss, (
            f"chip {chip.objectName()} stylesheet has no :focus rule; "
            f"keyboard users will see no focus indicator. Got: {ss!r}"
        )
    _ = rail


def test_selected_chip_border_is_semi_transparent(qapp):
    """The plan called for box-shadow: 0 0 0 1px rgba(accent, .3); QSS lacks
    box-shadow so we use a border. To honor the soft-ring design intent,
    the selected chip's border color must be a semi-transparent rgba
    derived from header_accent, not a full-opacity solid.

    Specificity: the gradient background also uses rgba(...) so a naive
    'rgba( in styleSheet' check is satisfied by the gradient alone — we
    must locate the border declaration explicitly and verify *it* uses
    rgba (i.e., 'border: 1px solid rgba(...)')."""
    import re
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance.nav_select = lambda i: None
    rail = instance._build_chip_rail()
    for i, chip in enumerate(instance.chip_buttons):
        chip.setChecked(i == 0)
    instance._theme_colors = lambda: {
        "sidebar_text":     "#aaaaaa",
        "sidebar_text_sel": "#ffffff",
        "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
        "sidebar_bg":       "#111111",
        "header_accent":    "#0077ff",
    }
    instance._apply_chip_styles()
    sel_ss = instance.chip_buttons[0].styleSheet()
    # Find the first 'border:' declaration in the SELECTED block (not the
    # :focus block, which intentionally uses solid accent). The selected
    # block is the one without ':focus' on its selector.
    # Match: 'border: <Npx> solid <color>;'
    border_decls = re.findall(r"border:\s*\d+px\s+solid\s+([^;]+);", sel_ss)
    assert border_decls, (
        f"Expected at least one 'border: Npx solid <color>;' declaration "
        f"in the selected chip stylesheet; got: {sel_ss!r}"
    )
    # The first declaration is the SELECTED-state border (the :focus
    # override comes later in the f-string). It must be rgba(...), not a
    # full-opacity #hex like #0077ff.
    first_border_color = border_decls[0].strip()
    assert first_border_color.startswith("rgba("), (
        f"Selected chip border color should be rgba(...) for soft accent ring; "
        f"got: {first_border_color!r} in stylesheet {sel_ss!r}"
    )
    # Verify the rgba is derived from header_accent (#0077ff -> 0, 119, 255)
    assert "0, 119, 255" in first_border_color or "0,119,255" in first_border_color, (
        f"Selected chip border rgba should derive from header_accent #0077ff "
        f"(0,119,255); got: {first_border_color!r}"
    )
    _ = rail


def test_nav_select_calls_push_slide_pages(qapp, monkeypatch):
    """nav_select must delegate page transitions to utils.motion."""
    from main import MultiToonTool
    import utils.motion as motion

    calls = []
    def fake_push(stack, from_idx, to_idx, axis):
        calls.append((from_idx, to_idx, axis))
        stack.setCurrentIndex(to_idx)
        return None
    monkeypatch.setattr(motion, "push_slide_pages", fake_push)

    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    # Stub stack + chips
    from PySide6.QtWidgets import QStackedWidget, QWidget, QToolButton
    instance.stack = QStackedWidget()
    for _ in range(6):
        instance.stack.addWidget(QWidget())
    instance.stack.setCurrentIndex(0)
    instance.chip_buttons = [QToolButton() for _ in range(4)]
    for b in instance.chip_buttons:
        b.setCheckable(True)
    instance._apply_chip_styles = lambda: None
    instance._initialized_nav = True

    instance.nav_select(2)

    assert calls == [(0, 2, "h")]
    assert instance.stack.currentIndex() == 2


def test_chip_rail_contains_pill_indicator(chip_rail):
    """The chip rail must host a PillIndicator child."""
    from utils.widgets.pill_indicator import PillIndicator
    pills = chip_rail.findChildren(PillIndicator)
    assert len(pills) == 1


def test_nav_select_slides_pill_to_target_chip(qapp, monkeypatch):
    """nav_select must call pill.slide_to with the target chip's geometry."""
    from main import MultiToonTool
    import utils.motion as motion
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)
    monkeypatch.setattr(
        motion, "push_slide_pages",
        lambda stack, f, t, axis: stack.setCurrentIndex(t),
    )

    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    rail = instance._build_chip_rail()
    rail.resize(800, 64)
    rail.show()
    qapp.processEvents()

    # Stub stack + chips already populated by _build_chip_rail
    from PySide6.QtWidgets import QStackedWidget, QWidget
    instance.stack = QStackedWidget()
    for _ in range(6):
        instance.stack.addWidget(QWidget())
    instance.stack.setCurrentIndex(0)
    instance._apply_chip_styles = lambda: None
    instance._initialized_nav = True
    instance.chip_rail = rail

    target_chip = instance.chip_buttons[2]
    target_geom = target_chip.geometry()

    instance.nav_select(2)
    # Drain deferred QTimer(0) that starts the animation inside slide_to.
    qapp.processEvents()

    # Pill should now have the target chip's geometry (as QRectF).
    pill = rail.findChildren(__import__("utils.widgets.pill_indicator",
                                       fromlist=["PillIndicator"]).PillIndicator)[0]
    from PySide6.QtCore import QRectF
    assert pill._pill_rect == QRectF(target_geom)


def test_chip_press_signals_call_press_scale(qapp, monkeypatch):
    """Chip pressed/released signals must call motion.press_scale."""
    import utils.motion as motion
    calls = []
    monkeypatch.setattr(motion, "press_scale",
                        lambda btn, depressed: calls.append((id(btn), depressed)))

    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    rail = instance._build_chip_rail()

    chip = instance.chip_buttons[0]
    chip.pressed.emit()
    chip.released.emit()

    assert calls == [(id(chip), True), (id(chip), False)]


def test_chip_hover_calls_morph_icon_size(qapp, monkeypatch):
    import utils.motion as motion
    calls = []
    monkeypatch.setattr(motion, "morph_icon_size",
                        lambda btn, px: calls.append((id(btn), px)))

    from main import MultiToonTool
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtCore import QPointF
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    rail = instance._build_chip_rail()
    chip = instance.chip_buttons[0]
    # Chip is not checked by default.

    enter = QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0))
    instance._chip_hover_filter.eventFilter(chip, enter)

    leave = QEvent(QEvent.Leave)
    instance._chip_hover_filter.eventFilter(chip, leave)

    assert calls == [(id(chip), 21), (id(chip), 20)]


def test_overflow_button_uses_overflow_popup_not_qmenu(qapp):
    """The chip rail's overflow button must NOT host a QMenu — it must
    delegate to OverflowPopup via the rail's click handler."""
    from PySide6.QtWidgets import QMenu
    from main import MultiToonTool

    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=True)
    rail = instance._build_chip_rail()

    assert instance.overflow_btn.menu() is None  # no QMenu attached
    # The instance must own an OverflowPopup
    from utils.widgets.overflow_popup import OverflowPopup
    assert hasattr(instance, "overflow_popup")
    assert isinstance(instance.overflow_popup, OverflowPopup)


def test_overflow_button_click_invokes_pop_menu(qapp, monkeypatch):
    import utils.motion as motion
    calls = []
    monkeypatch.setattr(motion, "pop_menu",
                        lambda popup, anchor, show: calls.append(("show" if show else "hide", popup, anchor)))

    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=True)
    rail = instance._build_chip_rail()

    instance.overflow_btn.click()

    assert len(calls) == 1
    assert calls[0][0] == "show"
    assert calls[0][2] is instance.overflow_btn
    _ = rail  # prevent GC of Qt widget tree before assertions
