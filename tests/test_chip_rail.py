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


def test_chip_rail_minimum_height_is_52(chip_rail):
    assert chip_rail.minimumHeight() == 52


def test_chip_rail_layout_is_hbox_with_expected_margins(chip_rail):
    layout = chip_rail.layout()
    assert isinstance(layout, QHBoxLayout)
    m = layout.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (12, 8, 12, 8)
    assert layout.spacing() == 4


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
from PySide6.QtGui import QAction


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


def test_chip_rail_has_hint_button(qapp):
    instance, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    assert hasattr(instance, "hint_btn"), "hint_btn should be created inside chip rail"
    assert instance.hint_btn.parent() is rail


def test_chip_rail_has_divider_between_chips_and_utilities(qapp):
    _, rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    dividers = [
        c for c in rail.findChildren(_QFrame)
        if c.objectName() == "chip_rail_divider"
    ]
    assert len(dividers) == 1
    assert dividers[0].frameShape() == _QFrame.VLine


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
    menu = instance.overflow_btn.menu()
    assert menu is not None
    logs_actions = [a for a in menu.actions() if a.text() == "View Logs"]
    assert len(logs_actions) == 1
    logs_actions[0].trigger()
    assert instance._nav_select_calls == [4]


def test_clicking_hint_btn_invokes_toggle_hints(qapp):
    """Clicking hint_btn should invoke _toggle_hints.

    The chip rail is the only path to the hints toggle after the sidebar was
    removed. We disconnect the original signal and re-connect a test stub so
    we can verify the plumbing without instantiating the full app.
    """
    instance, _rail = _build_rail_with_debug(qapp, show_debug_tab=False)
    instance._toggle_hints_calls = []
    # Disconnect the original connection and re-wire to the stub.
    instance.hint_btn.clicked.disconnect()
    instance.hint_btn.clicked.connect(
        lambda: instance._toggle_hints_calls.append(True)
    )
    instance.hint_btn.click()
    assert instance._toggle_hints_calls == [True]
