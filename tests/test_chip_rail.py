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
from PySide6.QtGui import QColor
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
    assert labels == ["Multitoon", "Launcher", "Keysets", "Settings"]


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


# The app icon moved from the chip rail to the header's top-left corner; its
# presence + click-to-Credits behavior is now covered in tests/test_app_header.py
# (test_header_has_app_icon_at_corner / test_header_app_icon_click_opens_credits).


def test_chip_rail_has_hint_button(qapp):
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    from PySide6.QtWidgets import QToolButton
    hint = rail.findChild(QToolButton, "hint_toggle")
    assert hint is not None, "hint toggle now lives in the chip rail"
    assert hint.size().width() == 34 and hint.size().height() == 34


def test_hint_button_parented_in_rail(qapp):
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    assert instance.hint_btn.parent() is rail


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


# Hint toggle now lives in the chip rail; see test_chip_rail_has_hint_button
# and test_hint_button_parented_in_rail above.


def test_apply_chip_styles_uniform_icon_size_and_font(qapp):
    """All chips render at the SAME icon size; selection is shown via the
    pill (a separate widget), icon color tint, and text color — not via
    size differential. Per-chip iconSize must be constant or the hover/press
    paint_scale animation would fight a state-driven iconSize snap."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance.nav_select = lambda i: None
    rail = instance._build_chip_rail()  # hold ref to prevent GC of child widgets
    # Pin selection to index 1 (Keysets) before styling
    for i, chip in enumerate(instance.chip_buttons):
        chip.setChecked(i == 1)
    instance._theme_colors = lambda: {
        "sidebar_text":     "#aaaaaa",
        "sidebar_text_sel": "#ffffff",
        "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
        "sidebar_bg":       "#111111",
        "header_accent":    "#0077ff",
    }
    instance._apply_chip_styles()
    # Every chip renders at the same icon size — no size cue for selection.
    sizes = [c.iconSize().width() for c in instance.chip_buttons]
    assert len(set(sizes)) == 1, (
        f"All chip icons should share one size; got {sizes!r}"
    )
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


def test_selected_chip_has_transparent_chip_border_and_accent_pill(qapp):
    """Selection is rendered by the PillIndicator (a hollow accent border that
    slides between chips), not by per-chip QSS. The chip itself must have a
    transparent border so the pill is visible around it, and the PillIndicator
    must carry the theme's accent color."""
    from main import MultiToonTool
    import re
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
    # The chip itself must NOT carry the selected border — the pill does.
    sel_ss = instance.chip_buttons[0].styleSheet()
    border_decls = re.findall(r"border:\s*\d+px\s+solid\s+([^;]+);", sel_ss)
    for color in border_decls:
        assert color.strip() == "transparent", (
            f"Selected chip border should be transparent (pill carries the "
            f"indicator); got: {color!r} in {sel_ss!r}"
        )
    # The PillIndicator must carry the theme accent color.
    assert instance.chip_pill._border_color.name(QColor.HexRgb).lower() == "#0077ff", (
        f"PillIndicator border should match header_accent; got "
        f"{instance.chip_pill._border_color.name()!r}"
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


def test_chip_press_drives_chipbutton_paint_scale(qapp):
    """Pressing the chip flips ChipButton's internal _is_pressed flag and
    targets the PRESS_SCALE paint_scale. ChipButton owns its own state
    machine; no external motion.press_scale call is involved."""
    from main import MultiToonTool
    from utils.widgets.chip_button import ChipButton
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    rail = instance._build_chip_rail()

    chip = instance.chip_buttons[0]
    assert isinstance(chip, ChipButton)
    assert chip._is_pressed is False
    assert chip._target_scale() == ChipButton.NORMAL_SCALE

    chip.pressed.emit()
    assert chip._is_pressed is True
    assert chip._target_scale() == ChipButton.PRESS_SCALE

    chip.released.emit()
    assert chip._is_pressed is False
    # Back to NORMAL (not still pressed and not hovered).
    assert chip._target_scale() == ChipButton.NORMAL_SCALE
    _ = rail


def test_chip_hover_drives_chipbutton_paint_scale(qapp):
    """Enter/Leave events flip _is_hovered and re-target paint_scale.
    ChipButton handles hover internally via enterEvent/leaveEvent —
    no external event filter is required."""
    from main import MultiToonTool
    from utils.widgets.chip_button import ChipButton
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(show_debug_tab=False)
    rail = instance._build_chip_rail()
    chip = instance.chip_buttons[0]
    assert isinstance(chip, ChipButton)
    assert chip._is_hovered is False

    enter = QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0))
    chip.enterEvent(enter)
    assert chip._is_hovered is True
    assert chip._target_scale() == ChipButton.HOVER_SCALE

    leave = QEvent(QEvent.Leave)
    chip.leaveEvent(leave)
    assert chip._is_hovered is False
    assert chip._target_scale() == ChipButton.NORMAL_SCALE
    _ = rail


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


def test_chip_rail_nav_items_order(qapp):
    """Pin the chip rail label order. The order is part of the UX contract -
    Launch must be index 1 (immediately after Multitoon) and Keysets must be
    index 2 (immediately before Settings), so Keysets groups with Settings as
    control-settings instead of sitting between Multitoon and Launch."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    instance.nav_select = lambda i: None
    rail = instance._build_chip_rail()
    labels = [c.text() for c in instance.chip_buttons]
    assert labels == ["Multitoon", "Launcher", "Keysets", "Settings"]


def test_chip_rail_phantoms_balance_clusters_debug_off(qapp):
    """Debug off: the left end is empty (app icon moved to the header corner).
    The left phantom = right cluster (hint 34) + one layout-spacing gap (4) = 38;
    there is no right phantom."""
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    lp = instance.chip_rail_left_phantom.sizeHint().width()
    assert lp == 38, f"expected left=38, got left={lp}"
    assert not hasattr(instance, "chip_rail_right_phantom")


def test_chip_rail_phantoms_balance_clusters_debug_on(qapp):
    """Debug on: right cluster = overflow(34)+spacing(4)+hint(34)=72; left phantom
    = 72 + one layout-spacing gap (4) = 76."""
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=True)
    lp = instance.chip_rail_left_phantom.sizeHint().width()
    assert lp == 76, f"expected left=76, got left={lp}"
    assert not hasattr(instance, "chip_rail_right_phantom")


@pytest.mark.parametrize("width", [575, 700])
@pytest.mark.parametrize("debug", [False, True])
def test_chip_rail_chips_are_visually_centered(qapp, debug, width):
    """The chips must sit at the rail's true geometric center (the whole point
    of the phantom spacer). Regression guard: removing the old left-corner app
    icon must not shift the chip cluster off-center. Asserts the ACTUAL laid-out
    geometry, not just spacer sizeHints, at the minimum (575) and a wider (700)
    rail width, for both debug states."""
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=debug)
    rail.resize(width, 44)
    rail.show()
    qapp.processEvents()
    rail.layout().activate()
    qapp.processEvents()
    geos = [c.geometry() for c in instance.chip_buttons]
    cluster_center = (min(g.left() for g in geos)
                      + max(g.right() for g in geos) + 1) / 2.0
    offset = cluster_center - rail.width() / 2.0
    rail.hide()
    assert abs(offset) <= 1.0, (
        f"chips off-center by {offset:+.1f}px (debug={debug}, width={width})")
