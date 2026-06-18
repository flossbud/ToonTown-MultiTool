"""Regression: the 5s auto-refresh must not judder the toon name labels or
shift the bottom-row portrait circles in the compact pinwheel layout.

Root cause (fixed): the shared ``_refresh_toon_name_labels`` re-applied a stale
``font-size: 21px`` stylesheet on every refresh, fighting the layout-owned
``setFont(23)`` from ``_CompactLayout._populate_cell``. Each cycle the name
flipped 23 -> 21 -> 23 (visible judder), and the 3 px sizeHint delta nudged the
bottom row of portraits down/up whenever the 2x2 grid had little vertical slack
(the app's default window height). The name font + colour are owned by the
active layout (compact ``setFont`` + ``set_card_brand`` colour), so the refresh
must touch only the label TEXT.

The assertions sample the TRANSIENT state: immediately after the synchronous
refresh write, BEFORE the deferred ``_refresh_chrome_after_name_change`` restore
that masks the flip a tick later. Measured at 880x614 (the compact
``minimumSizeHint`` regime) where any name-height change would move the bottom
row.
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return list(self.ttr_window_ids)

    def get_active_window(self):
        return None

    def clear_window_ids(self):
        self.ttr_window_ids = []

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


def _make_tab(monkeypatch, tmp_path):
    # IRON LAW: isolate HOME + config dir BEFORE importing the tab module.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    return MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def test_auto_refresh_does_not_judder_name_or_shift_portraits(
    qt_app, monkeypatch, tmp_path,
):
    tab = _make_tab(monkeypatch, tmp_path)
    tab.window_manager.ttr_window_ids = [101, 102, 103, 104]
    tab.toon_names = ["Flossbud", "Linux", "Pinkerton", "Spot"]
    tab.enabled_toons = [True, True, True, True]
    tab.service_running = True
    for i in range(4):
        tab.slot_badges[i].set_game("ttr")

    tab._stack.setCurrentWidget(tab._compact)
    tab.resize(880, 614)  # compact minimumSizeHint regime: little vertical slack
    tab.show()
    qt_app.processEvents()

    # Establish the STEADY state: end on a set_card_brand pass so the name
    # label's last style write is the no-font-size colour stylesheet, letting
    # the layout-owned setFont(23) take effect (height 27, pixelSize 23).
    tab._compact._apply_initial_brands()
    qt_app.processEvents()

    def portrait_ys():
        return [c["portrait_frame"].mapTo(tab, QPoint(0, 0)).y()
                for c in tab._compact._cells]

    def name_px():
        return [lbl.font().pixelSize() for (lbl, _) in tab.toon_labels]

    def name_h():
        return [lbl.sizeHint().height() for (lbl, _) in tab.toon_labels]

    base_y, base_px, base_h = portrait_ys(), name_px(), name_h()

    # The synchronous refresh write — what runs first on every 5s cycle, a tick
    # before the deferred chrome restore. Sample the transient immediately.
    tab._refresh_toon_name_labels()
    qt_app.processEvents()

    assert name_px() == base_px, (
        f"name font pixelSize changed on refresh: {base_px} -> {name_px()}; "
        f"a stale font-size stylesheet is fighting the layout-owned font"
    )
    assert name_h() == base_h, (
        f"name label sizeHint height changed on refresh: {base_h} -> {name_h()}"
    )
    assert portrait_ys() == base_y, (
        f"portrait rows shifted on refresh: {base_y} -> {portrait_ys()}; "
        f"the bottom-row circles judder"
    )
