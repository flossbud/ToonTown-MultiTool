"""Offscreen UI tests: click sync buttons exist, gate on the setting, and
talk to the service. Uses the same construction pattern as the existing
offscreen multitoon tab tests (test_card_accent_override.py)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


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
    # settings_manager.set(...) alone must reveal the buttons: the on_change
    # registration in _build_click_sync is the wiring under test. Like the
    # keep-alive button, presence does NOT depend on detected windows.
    tab.settings_manager.set("click_sync_enabled", True)
    assert all(b.isVisibleTo(b.parentWidget()) for b in tab.click_sync_buttons)


def test_windowless_slot_is_disabled_not_hidden(multitoon_tab):
    tab = multitoon_tab
    tab.settings_manager.set("click_sync_enabled", True)
    c = tab._c()
    btn = tab.click_sync_buttons[0]  # no windows in the fake WM
    assert btn.isVisibleTo(btn.parentWidget())
    assert not btn.isEnabled()
    assert c["btn_disabled"] in btn.styleSheet()
    assert "no toon detected" in btn.toolTip()
    # A TTR window appearing re-enables the slot.
    _fill_ttr_slots(tab)
    tab._apply_click_sync_visibility()
    assert btn.isEnabled()


def test_orphaned_member_stays_clickable(multitoon_tab):
    # A member whose window vanished shows error AND remains enabled: the
    # button is the only affordance to evict it and unpause the group.
    tab = multitoon_tab
    tab.settings_manager.set("click_sync_enabled", True)
    tab.click_sync_service.slot_states_changed.emit(
        {0: "error", 1: "armed", 2: "off", 3: "off"})
    c = tab._c()
    btn = tab.click_sync_buttons[0]  # member, but no window in the fake WM
    assert btn.isEnabled()
    assert c["accent_red"] in btn.styleSheet()


def test_toggle_calls_service(multitoon_tab):
    tab = multitoon_tab
    calls = []
    tab.click_sync_service.toggle_slot = lambda idx: calls.append(idx) or True
    tab.toggle_click_sync(2)
    assert calls == [2]


def test_service_error_sets_failure_tooltip(multitoon_tab):
    # A capture failure must NOT leave the generic mismatch tooltip on the
    # member buttons (it would send the user resizing windows instead of
    # retrying). The service emits error STATES first, then service_error;
    # the override applies to slots whose cached state is "error".
    tab = multitoon_tab
    svc = tab.click_sync_service
    svc.slot_states_changed.emit({0: "error", 1: "error", 2: "off", 3: "off"})
    svc.service_error.emit("mouse capture unavailable")
    for i in (0, 1):
        tip = tab.click_sync_buttons[i].toolTip()
        assert "mouse capture unavailable" in tip
        assert "proportions" not in tip
    # Non-member button keeps its default tooltip.
    assert "stopped" not in tab.click_sync_buttons[2].toolTip()
    # Recovery: any fresh snapshot supersedes the override.
    svc.slot_states_changed.emit({0: "active", 1: "active", 2: "off", 3: "off"})
    assert "stopped" not in tab.click_sync_buttons[0].toolTip()


def test_state_styles_follow_palette(multitoon_tab):
    tab = multitoon_tab
    _fill_ttr_slots(tab)  # windowless slots render disabled, not off
    svc = tab.click_sync_service
    svc.slot_states_changed.emit({0: "armed", 1: "active", 2: "error", 3: "off"})
    c = tab._c()
    s0 = tab.click_sync_buttons[0].styleSheet()
    assert c["accent_pink_border"] in s0 and c["toon_btn_inactive_bg"] in s0
    assert c["accent_pink"] in tab.click_sync_buttons[1].styleSheet()
    assert c["accent_red"] in tab.click_sync_buttons[2].styleSheet()
    s3 = tab.click_sync_buttons[3].styleSheet()
    assert c["toon_btn_inactive_border"] in s3
    assert c["accent_pink"] not in s3


def test_unknown_state_resolves_off(multitoon_tab):
    tab = multitoon_tab
    _fill_ttr_slots(tab)  # windowless slots render disabled, not off
    tab.click_sync_service.slot_states_changed.emit(
        {0: "garbage", 1: "off", 2: "off", 3: "off"})
    c = tab._c()
    assert c["toon_btn_inactive_bg"] in tab.click_sync_buttons[0].styleSheet()


def test_error_icon_swaps_and_recovers(multitoon_tab):
    tab = multitoon_tab
    svc = tab.click_sync_service
    svc.slot_states_changed.emit({0: "active", 1: "off", 2: "off", 3: "off"})
    active_key = tab.click_sync_buttons[0].icon().cacheKey()
    svc.slot_states_changed.emit({0: "error", 1: "off", 2: "off", 3: "off"})
    assert tab.click_sync_buttons[0].icon().cacheKey() != active_key
    svc.slot_states_changed.emit({0: "active", 1: "off", 2: "off", 3: "off"})
    assert tab.click_sync_buttons[0].icon().cacheKey() == active_key


def test_master_toggle_restores_state_styling(multitoon_tab):
    # End-to-end through the REAL service: members whose windows can't
    # resolve (fake WM has no geometry) style as error (red); master OFF
    # emits all-off (gray); master ON restores the retained membership's
    # states (red again). Pins emission -> resolver styling round trips.
    tab = multitoon_tab
    _fill_ttr_slots(tab)  # windowless slots render disabled, not off
    svc = tab.click_sync_service
    c = tab._c()
    svc.set_enabled(True)
    svc.toggle_slot(0)
    svc.toggle_slot(1)
    assert c["accent_red"] in tab.click_sync_buttons[0].styleSheet()
    svc.set_enabled(False)  # emits a real all-off snapshot
    assert c["toon_btn_inactive_bg"] in tab.click_sync_buttons[0].styleSheet()
    assert c["accent_red"] not in tab.click_sync_buttons[0].styleSheet()
    svc.set_enabled(True)   # membership retained: states re-emit
    assert c["accent_red"] in tab.click_sync_buttons[0].styleSheet()


def test_theme_refresh_rebuilds_icon_cache(multitoon_tab):
    tab = multitoon_tab
    tab.click_sync_service.slot_states_changed.emit(
        {0: "active", 1: "off", 2: "off", 3: "off"})
    before = tab._click_sync_icons["active"].cacheKey()
    tab.refresh_theme()
    assert tab._click_sync_icons["active"].cacheKey() != before
