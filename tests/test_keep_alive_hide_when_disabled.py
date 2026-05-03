"""Tests for the keep-alive hide-when-disabled feature."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettingsManager:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        pass


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


@pytest.fixture
def tab(qapp):
    from tabs.multitoon_tab import MultitoonTab
    return MultitoonTab(
        settings_manager=_FakeSettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def test_compact_ctrl_row_contains_nested_middle_layout(tab):
    """After build_ui, each compact card's ctrl_row should be:
    [enable_btn, middle (HBoxLayout containing ka_group + addStretch), selector]"""
    slot_zero = tab._compact._card_slots[0]
    ctrl_row = slot_zero["ctrl_row"]

    # ctrl_row should have 3 items: enable_btn (widget), middle (sub-layout), selector (widget)
    assert ctrl_row.count() == 3, (
        f"ctrl_row should have 3 items (enable, middle, selector); got {ctrl_row.count()}"
    )

    # Item 1 (middle) must be a QHBoxLayout (not a widget)
    middle_item = ctrl_row.itemAt(1)
    middle_layout = middle_item.layout()
    assert isinstance(middle_layout, QHBoxLayout), (
        f"ctrl_row item 1 should be a QHBoxLayout (middle); got {type(middle_layout)}"
    )

    # middle should have 2 items: ka_group widget + a stretch spacer
    assert middle_layout.count() == 2, (
        f"middle should have 2 items (ka_group, addStretch); got {middle_layout.count()}"
    )
    # Item 0: ka_group widget
    assert middle_layout.itemAt(0).widget() is slot_zero["ka_group"], (
        "middle item 0 should be ka_group"
    )
    # Item 1: spacer (stretch). spacerItem() returns the QSpacerItem if it's a stretch.
    assert middle_layout.itemAt(1).spacerItem() is not None, (
        "middle item 1 should be a stretch spacer"
    )
