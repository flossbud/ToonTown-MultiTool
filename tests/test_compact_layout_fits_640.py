"""Pin the compact multitoon layout to fit in the 650 px content budget
(default 770-tall window minus 56 header minus 64 chip rail). The window
default grew by 10 px during the Direction D redesign (per
docs/superpowers/specs/2026-05-24-multitoon-tab-compact-redesign-design.md);
the budget moved in lockstep."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


# Direction D redesign: budget bumped to 650 (770 default - 56 - 64) and
# the natural height changed because we removed the outer card and grew
# the per-card headers. See spec
# docs/superpowers/specs/2026-05-24-multitoon-tab-compact-redesign-design.md
CONTENT_BUDGET_PX = 650  # 770 default window - 56 header - 64 chip rail
CONTENT_WIDTH_PX = 549   # default 575 min-width window minus 12+12 outer margins minus 2 border
_PIN_HEIGHT_PX = 624     # measured natural height after the header-restack (21 px name); +4 px grace


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
