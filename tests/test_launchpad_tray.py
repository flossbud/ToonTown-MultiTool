"""Launchpad tray icon: the quick menu rows, their signals, the running
state, the tooltip, and the TRAY_ICON setting followed live. The offscreen
platform has no tray, so a stand-in replaces QSystemTrayIcon."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from utils import settings_keys as sk
from utils.widgets.launchpad.tray import LaunchpadTray


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self._cbs = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        for cb in list(self._cbs):
            cb(key, value)

    def on_change(self, cb):
        self._cbs.append(cb)


class _FakeTray(QObject):
    activated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.visible = False
        self.icon = None
        self.tip = ""
        self.menu = None

    def setIcon(self, icon):
        self.icon = icon

    def setToolTip(self, tip):
        self.tip = tip

    def toolTip(self):
        return self.tip

    def setContextMenu(self, menu):
        self.menu = menu

    def contextMenu(self):
        return self.menu

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def isVisible(self):
        return self.visible


def _tray(data=None, available=True):
    sm = _Settings(data)
    t = LaunchpadTray(sm, icon=QIcon(), tray_factory=_FakeTray,
                      available=lambda: available)
    return t, sm


def _texts(menu):
    return [a.text() if not a.isSeparator() else "---" for a in menu.actions()]


def test_menu_rows_in_order(qapp):
    t, _ = _tray()
    assert t.tray.menu is t.menu
    assert _texts(t.menu) == ["Launch accounts", "Settings", "Open MultiTool", "---",
                              "Start all toons", "Quit MultiTool"]
    assert all(not a.icon().isNull() for a in t.menu.actions() if not a.isSeparator())


@pytest.mark.parametrize("action,signal", [
    ("launch_action", "launch_accounts_requested"),
    ("settings_action", "settings_requested"),
    ("open_action", "open_requested"),
    ("quit_action", "quit_requested"),
])
def test_each_row_emits_its_signal(qapp, action, signal):
    t, _ = _tray()
    seen = []
    getattr(t, signal).connect(lambda: seen.append(1))
    getattr(t, action).trigger()
    assert seen == [1]


def test_stop_start_follows_running(qapp):
    t, _ = _tray()
    stops, starts = [], []
    t.stop_all_requested.connect(lambda: stops.append(1))
    t.start_all_requested.connect(lambda: starts.append(1))
    t.toggle_action.trigger()
    assert starts == [1] and stops == []
    t.set_running(True)
    assert t.toggle_action.text() == "Stop all toons"
    t.toggle_action.trigger()
    assert stops == [1]
    t.set_running(False)
    assert t.toggle_action.text() == "Start all toons"


def test_running_count_hint_and_tooltip(qapp):
    t, _ = _tray()
    assert t.tray.tip == "ToonTown MultiTool\nNo toons running"
    t.set_running(True)
    t.set_running_count(3)
    assert t.launch_action.text() == "Launch accounts\t3 running ›"
    assert t.tray.tip == "ToonTown MultiTool\n3 toons running"
    t.set_running_count(1)
    assert t.tray.tip.endswith("1 toon running")
    t.set_running(False)
    assert t.tray.tip.endswith("1 toon running · stopped")
    t.set_running_count(0)
    assert t.launch_action.text() == "Launch accounts"


def test_clicking_the_icon_opens(qapp):
    t, _ = _tray()
    seen = []
    t.open_requested.connect(lambda: seen.append(1))
    t.tray.activated.emit(QSystemTrayIcon.Trigger)
    t.tray.activated.emit(QSystemTrayIcon.DoubleClick)
    t.tray.activated.emit(QSystemTrayIcon.Context)
    assert seen == [1, 1]


def test_shown_by_default_and_follows_the_setting_live(qapp):
    t, sm = _tray()
    assert t.is_shown() and t.reachable()
    sm.set(sk.TRAY_ICON, False)
    assert not t.is_shown() and not t.reachable()
    sm.set(sk.TRAY_ICON, True)
    assert t.is_shown()
    sm.set("theme", "dark")                       # unrelated keys change nothing
    assert t.is_shown()


def test_setting_off_at_start_hides(qapp):
    t, _ = _tray({sk.TRAY_ICON: False})
    assert not t.is_shown()


def test_never_shown_without_a_system_tray(qapp):
    t, sm = _tray(available=False)
    assert not t.available() and not t.is_shown() and not t.reachable()
    sm.set(sk.TRAY_ICON, True)
    assert not t.is_shown()


def test_available_wraps_qt_by_default(qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    t = LaunchpadTray(_Settings(), icon=QIcon(), tray_factory=_FakeTray)
    assert t.available()
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    assert not t.available()


def test_default_icon_is_the_app_icon(qapp):
    t = LaunchpadTray(_Settings(), tray_factory=_FakeTray, available=lambda: False)
    assert t.tray.icon is not None and not t.tray.icon.isNull()


def test_real_tray_icon_constructs_offscreen(qapp):
    """With the real QSystemTrayIcon (no tray offscreen): builds, is never
    shown, and its menu is attached."""
    t = LaunchpadTray(_Settings())
    assert isinstance(t.tray, QSystemTrayIcon)
    assert t.tray.contextMenu() is t.menu
    if not QSystemTrayIcon.isSystemTrayAvailable():
        assert not t.tray.isVisible()


def test_shutdown_removes_the_icon_for_good(qapp):
    t, sm = _tray()
    assert t.is_shown()
    t.shutdown()
    assert not t.is_shown() and t.tray.menu is None
    sm.set(sk.TRAY_ICON, True)                     # a late setting change
    assert not t.is_shown()
