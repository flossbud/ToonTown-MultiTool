"""Tests for chip-rail construction in MultiToonTool.

Same pattern as test_app_header.py: bypass __init__ via __new__ and call
the build method directly.

The settings_manager stub here is forward-compatible scaffolding — the
current _build_chip_rail body does not read it. It will be read once
Task 4 adds the hint toggle and the debug-gated overflow menu, both of
which probe settings at construction time.
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
    for chip in rail.findChildren(QToolButton):
        if chip.objectName().startswith("chip_"):
            assert chip.toolButtonStyle() == Qt.ToolButtonTextUnderIcon


def test_chips_are_checkable(chip_rail_with_nav):
    _, rail = chip_rail_with_nav
    for chip in rail.findChildren(QToolButton):
        if chip.objectName().startswith("chip_"):
            assert chip.isCheckable()


def test_clicking_chip_calls_nav_select_with_correct_index(chip_rail_with_nav):
    instance, rail = chip_rail_with_nav
    chips = [c for c in rail.findChildren(QToolButton) if c.objectName().startswith("chip_")]
    # Click Keymap (index 2)
    chips[2].click()
    assert instance._nav_select_calls == [2]
