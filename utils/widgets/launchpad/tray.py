"""Tray icon carrying the strips' quick menu (float-strip handoff section 6).

A QSystemTrayIcon with a native QMenu:

    Launch accounts          N running ›
    Settings
    Open MultiTool
    ─────────────
    Stop all toons  /  Start all toons
    Quit MultiTool

Each row emits its own signal; the window decides what it means (the
lifecycle's `requested` for Launch accounts / Settings / Open MultiTool,
the session's stop/start, the app's quit route). Clicking the icon itself
emits open_requested. The tooltip carries the session status.

The icon is shown only while the TRAY_ICON setting is on, and follows the
setting live. available() is False where the platform has no tray (the
lifecycle then minimizes instead of hiding); the icon is never shown there.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from utils import settings_keys as sk
from utils.icon_factory import (
    make_nav_gear, make_nav_power, make_play_icon, make_stop_icon, make_window_icon,
    make_x_icon,
)

APP_NAME = "ToonTown MultiTool"
ROW_COLORS = {"launch": "#E05252", "settings": "#3da343", "open": "#0077ff",
              "toggle": "#888888", "quit": "#888888"}


def _app_icon() -> QIcon:
    icon = QApplication.windowIcon()
    if icon is not None and not icon.isNull():
        return icon
    from utils.asset_paths import asset_path
    return QIcon(asset_path("multitool.png"))


class LaunchpadTray(QObject):
    launch_accounts_requested = Signal()
    settings_requested = Signal()
    open_requested = Signal()
    stop_all_requested = Signal()
    start_all_requested = Signal()
    quit_requested = Signal()

    def __init__(self, settings_manager, icon: QIcon | None = None, parent=None,
                 tray_factory: Callable[[QObject], object] | None = None,
                 available: Callable[[], bool] | None = None):
        super().__init__(parent)
        self._sm = settings_manager
        self._running = False
        self._count = 0
        # Looked up on every call: a tray can appear after start (a panel
        # restarting), so availability is never cached.
        self._available_fn = available or (lambda: QSystemTrayIcon.isSystemTrayAvailable())
        factory = tray_factory or (lambda owner: QSystemTrayIcon(owner))
        self.tray = factory(self)
        self.tray.setIcon(icon if icon is not None else _app_icon())

        self.menu = QMenu()
        self.launch_action = self.menu.addAction(
            make_nav_power(16, QColor(ROW_COLORS["launch"])), "Launch accounts")
        self.launch_action.triggered.connect(self.launch_accounts_requested.emit)
        self.settings_action = self.menu.addAction(
            make_nav_gear(16, QColor(ROW_COLORS["settings"])), "Settings")
        self.settings_action.triggered.connect(self.settings_requested.emit)
        self.open_action = self.menu.addAction(
            make_window_icon(16, QColor(ROW_COLORS["open"])), "Open MultiTool")
        self.open_action.triggered.connect(self.open_requested.emit)
        self.menu.addSeparator()
        self.toggle_action = self.menu.addAction("")
        self.toggle_action.triggered.connect(self._on_toggle)
        self.quit_action = self.menu.addAction(
            make_x_icon(16, QColor(ROW_COLORS["quit"])), "Quit MultiTool")
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

        self._refresh_rows()
        if hasattr(self._sm, "on_change"):
            self._sm.on_change(self._on_setting_changed)
        self.sync_visibility()

    # ── public API ──────────────────────────────────────────────────────
    def available(self) -> bool:
        """Whether this platform has a system tray at all."""
        try:
            return bool(self._available_fn())
        except Exception:
            return False

    def enabled(self) -> bool:
        return bool(self._sm.get(sk.TRAY_ICON, sk.TRAY_ICON_DEFAULT))

    def is_shown(self) -> bool:
        return bool(self.tray.isVisible())

    def reachable(self) -> bool:
        """True while the tray icon can bring the window back: the lifecycle's
        tray input."""
        return self.available() and self.enabled()

    def set_running(self, running: bool) -> None:
        """Broadcast service state: flips Stop all / Start all."""
        self._running = bool(running)
        self._refresh_rows()

    def set_running_count(self, n: int) -> None:
        """Live toons: the Launch accounts hint and the tooltip."""
        self._count = max(0, int(n))
        self._refresh_rows()

    def sync_visibility(self) -> None:
        if self.reachable():
            self.tray.show()
        else:
            self.tray.hide()

    # ── internals ───────────────────────────────────────────────────────
    def _refresh_rows(self) -> None:
        hint = f"\t{self._count} running ›" if self._count else ""
        self.launch_action.setText(f"Launch accounts{hint}")
        if self._running:
            self.toggle_action.setText("Stop all toons")
            self.toggle_action.setIcon(make_stop_icon(16, QColor(ROW_COLORS["toggle"])))
        else:
            self.toggle_action.setText("Start all toons")
            self.toggle_action.setIcon(make_play_icon(16, QColor(ROW_COLORS["toggle"])))
        if self._count == 0:
            status = "No toons running"
        elif self._count == 1:
            status = "1 toon running"
        else:
            status = f"{self._count} toons running"
        if self._count and not self._running:
            status += " · stopped"
        self.tray.setToolTip(f"{APP_NAME}\n{status}")

    def _on_toggle(self) -> None:
        if self._running:
            self.stop_all_requested.emit()
        else:
            self.start_all_requested.emit()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_requested.emit()

    def _on_setting_changed(self, key, _value) -> None:
        if key == sk.TRAY_ICON:
            self.sync_visibility()
