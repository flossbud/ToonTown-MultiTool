"""Pin the compact multitoon layout to fit in the new 640 px content budget
(default 748-tall window minus 56 header minus 52 chip rail)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


CONTENT_BUDGET_PX = 640  # 748 default window - 56 header - 52 chip rail
CONTENT_WIDTH_PX = 528   # default 560 window minus app left/right margins
_PIN_HEIGHT_PX = 636     # measured natural height 634; 2px grace for measurement noise


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build_compact_layout(qapp):
    """Build a real MultitoonTab in compact mode against minimal fake managers."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtCore import QObject, Signal

    class _FakeSettingsManager:
        def __init__(self):
            self._data = {}

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

    tab = MultitoonTab(
        settings_manager=_FakeSettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    tab.set_layout_mode("compact")
    tab.resize(CONTENT_WIDTH_PX, CONTENT_BUDGET_PX)
    return tab


def test_compact_layout_fits_in_640px_budget(qapp):
    tab = _build_compact_layout(qapp)
    # sizeHint reflects the natural height the layout wants. After tightening
    # the new budget must accommodate it.
    natural_height = tab.sizeHint().height()
    assert natural_height <= _PIN_HEIGHT_PX, (
        f"Compact multitoon natural height {natural_height} > {_PIN_HEIGHT_PX} pin "
        f"(budget is {CONTENT_BUDGET_PX})."
    )
