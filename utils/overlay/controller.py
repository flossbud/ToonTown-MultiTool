"""Owns the Framed <-> Transparent window-mode transition for MultiToonTool.

Phase 1 scope: chrome show/hide + snapshot/restore + backend-availability gate.
Later phases extend enter/leave with window flags, the cluster host, the input
region, gestures, and persistence (see _apply_overlay/_remove_overlay hooks)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from utils.overlay.mode import WindowMode

_CHROME_ATTRS = ("header", "chip_rail", "update_banner", "admin_notice_banner")


class WindowModeController(QObject):
    mode_changed = Signal(object)  # WindowMode

    def __init__(self, window, backend, settings, parent=None):
        super().__init__(parent)
        self._win = window
        self._backend = backend
        self._settings = settings
        self._mode = WindowMode.FRAMED
        self._snapshot: dict | None = None

    def mode(self) -> WindowMode:
        return self._mode

    def can_enter(self) -> bool:
        return bool(self._backend.is_available())

    def toggle(self) -> None:
        if self._mode is WindowMode.FRAMED:
            self.enter_transparent()
        else:
            self.leave_transparent()

    def enter_transparent(self) -> None:
        if self._mode is WindowMode.TRANSPARENT or not self.can_enter():
            return
        self._snapshot = self._capture()
        for name in _CHROME_ATTRS:
            getattr(self._win, name).hide()
        self._win.stack.setCurrentWidget(self._win.multitoon_tab)
        self._apply_overlay()
        self._mode = WindowMode.TRANSPARENT
        self.mode_changed.emit(self._mode)

    def leave_transparent(self) -> None:
        if self._mode is WindowMode.FRAMED:
            return
        self._remove_overlay()
        self._restore(self._snapshot or {})
        self._mode = WindowMode.FRAMED
        self.mode_changed.emit(self._mode)

    # --- hooks extended by later phases (Phase 2-3-7) ---
    def _apply_overlay(self) -> None:
        """Phase 2+: window flags/translucency/on-top, size to cluster, set input region."""
        pass

    def _remove_overlay(self) -> None:
        """Phase 2+: clear input region, restore flags."""
        pass

    # --- snapshot/restore ---
    def _capture(self) -> dict:
        return {
            "active_index": self._win.stack.currentIndex(),
            "chrome_visible": {n: getattr(self._win, n).isVisible() for n in _CHROME_ATTRS},
            "geometry": self._win.geometry(),
        }

    def _restore(self, snap: dict) -> None:
        for name, vis in snap.get("chrome_visible", {}).items():
            getattr(self._win, name).setVisible(vis)
        if "active_index" in snap:
            self._win.stack.setCurrentIndex(snap["active_index"])
        if "geometry" in snap:
            self._win.setGeometry(snap["geometry"])
