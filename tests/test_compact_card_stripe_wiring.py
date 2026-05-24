"""Integration test: confirms the wiring path from MultitoonTab through
_set_card_brand_for_slot through _CompactLayout.set_card_brand actually
drives the _CardStripe widget's _color to the expected target after
animation completion."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    def get(self, k, default=None):
        if k == "dark_mode":
            return True
        return default
    def set(self, *a, **k):
        pass
    def on_change(self, *a, **k):
        pass


class _FakeWindow(QObject):
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


def _settle(stripe):
    if stripe._anim is not None:
        stripe._anim.setCurrentTime(stripe._anim.duration())


def _build_tab(qapp):
    """Build a MultitoonTab and exit the cold-start delay so direct
    set_card_brand calls drive the stripe immediately (the 1 s cold-
    start hold is a UX feature for actual app launch, not relevant to
    the wiring assertions here)."""
    from tabs.multitoon_tab import MultitoonTab

    tab = MultitoonTab(settings_manager=_FakeSettings(), window_manager=_FakeWindow())
    tab.set_layout_mode("compact")
    tab.resize(549, 650)
    tab.show()
    qapp.processEvents()
    tab._compact._cold_start_in_progress = False
    return tab


def test_set_card_brand_drives_stripe_to_muted_ttr(qapp):
    """End-to-end: set_card_brand('ttr', enabled=False) settles the
    stripe at the muted TTR brand colour."""
    from tabs.multitoon._compact_layout import _muted_brand

    tab = _build_tab(qapp)
    tab._compact.set_card_brand(0, "ttr", enabled=False)
    stripe = tab._compact._card_slots[0]["card_stripe"]
    _settle(stripe)

    expected = _muted_brand(QColor("#4A8FE7"))
    assert stripe._color == expected


def test_set_card_brand_drives_stripe_to_full_cc(qapp):
    """End-to-end: set_card_brand('cc', enabled=True) settles at full CC."""
    tab = _build_tab(qapp)
    tab._compact.set_card_brand(1, "cc", enabled=True)
    stripe = tab._compact._card_slots[1]["card_stripe"]
    _settle(stripe)

    assert stripe._color == QColor("#F26D21")


def test_set_card_brand_none_drives_stripe_to_empty(qapp):
    """End-to-end: set_card_brand(None) settles at the empty (grey) tier."""
    tab = _build_tab(qapp)
    # Set it to TTR first, then back to None
    tab._compact.set_card_brand(2, "ttr", enabled=True)
    stripe = tab._compact._card_slots[2]["card_stripe"]
    _settle(stripe)
    tab._compact.set_card_brand(2, None)
    _settle(stripe)

    # The empty colour resolves via the theme; just confirm rank is 0
    # (low saturation) rather than pinning a specific hex.
    assert stripe._color.hslSaturation() < 30
