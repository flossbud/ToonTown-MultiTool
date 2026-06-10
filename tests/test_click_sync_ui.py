"""Offscreen UI tests: click sync buttons exist, gate on the setting, and
talk to the service. Uses the same construction pattern as the existing
offscreen multitoon tab tests (test_card_accent_override.py)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only feature")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    window_geometry_updated = Signal()

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.window_ids = []
        self.window_games = {}

    def get_window_ids(self): return list(self.window_ids)
    def get_window_geometry(self, wid): return None
    def get_active_window(self): return None
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


@pytest.fixture
def multitoon_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    try:
        yield tab
    finally:
        # Non-daemon service threads hang pytest if left running.
        tab.input_service.shutdown()
        if tab.click_sync_service is not None:
            tab.click_sync_service.shutdown()
        if tab._click_sync_backend is not None:
            tab._click_sync_backend.disconnect()


def _fill_ttr_slots(tab):
    wm = tab.window_manager
    wm.window_ids = ["0x1", "0x2", "0x3", "0x4"]
    wm.window_games = {wid: "ttr" for wid in wm.window_ids}


def test_buttons_exist_and_hidden_by_default(multitoon_tab):
    tab = multitoon_tab
    assert len(tab.click_sync_buttons) == 4
    # isHidden, not "not isVisible": isVisible is vacuously False on an
    # unshown tab, so it would pass even if the buttons were never hidden.
    assert all(b.isHidden() for b in tab.click_sync_buttons)


def test_master_switch_reveals_buttons(multitoon_tab):
    tab = multitoon_tab
    _fill_ttr_slots(tab)
    # settings_manager.set(...) alone must reveal the buttons: the on_change
    # registration in _build_click_sync is the wiring under test.
    tab.settings_manager.set("click_sync_enabled", True)
    assert all(b.isVisibleTo(b.parentWidget()) for b in tab.click_sync_buttons)


def test_toggle_calls_service(multitoon_tab):
    tab = multitoon_tab
    calls = []
    tab.click_sync_service.toggle_slot = lambda idx: calls.append(idx) or True
    tab.toggle_click_sync(2)
    assert calls == [2]


def test_service_error_sets_failure_tooltip(multitoon_tab):
    # A capture failure must NOT leave the generic mismatch tooltip on the
    # member buttons (it would send the user resizing windows instead of
    # retrying). The service emits error states first, then service_error.
    tab = multitoon_tab
    tab.click_sync_buttons[0].setChecked(True)
    tab.click_sync_buttons[1].setChecked(True)
    tab.click_sync_service.service_error.emit("mouse capture unavailable")
    for i in (0, 1):
        tip = tab.click_sync_buttons[i].toolTip()
        assert "mouse capture unavailable" in tip
        assert "proportions" not in tip
    # Non-member button keeps its default tooltip.
    assert "stopped" not in tab.click_sync_buttons[2].toolTip()
