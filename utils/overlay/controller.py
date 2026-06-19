"""Owns the Framed <-> Transparent window-mode transition for MultiToonTool.

Phase 1 scope: chrome show/hide + snapshot/restore + backend-availability gate.
Phase 3 scope: window flags/translucency/on-top, cluster host embed, input region,
scale-by-notch. Later phases add gestures and persistence."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from utils.overlay.cluster_host import ClusterHost
from utils.overlay.mode import WindowMode
from utils.overlay.region import build_input_region
from utils.overlay.scale import step_scale

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
        self._host: ClusterHost | None = None
        self._overlay_state: dict | None = None

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

    # --- overlay hooks (Phase 3) ---
    def _apply_overlay(self) -> None:
        mt = self._win.multitoon_tab
        compact = mt._compact
        self._overlay_state = {
            "flags": self._win.windowFlags(),
            "min_size": self._win.minimumSize(),
            "compact_index": mt._stack.indexOf(compact),
        }
        captured = compact.size()
        self._host = ClusterHost(compact, content_size=captured)
        self._win.stack.hide()
        self._win.container.layout().addWidget(self._host)
        self._win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._win.setAttribute(Qt.WA_TranslucentBackground, True)
        self._win.setMinimumSize(0, 0)
        self._win.show()
        self._backend.set_overlay_hints(self._win)
        self._win.resize(self._host.size())
        self.update_region()

    def _remove_overlay(self) -> None:
        self._backend.clear_input_region(self._win)
        mt = self._win.multitoon_tab
        compact = mt._compact
        mt._stack.insertWidget(self._overlay_state["compact_index"], compact)
        mt._stack.setCurrentWidget(compact)
        self._win.container.layout().removeWidget(self._host)
        self._host.setParent(None)
        self._host.deleteLater()
        self._host = None
        self._win.setWindowFlags(self._overlay_state["flags"])
        self._win.setMinimumSize(self._overlay_state["min_size"])
        self._win.stack.show()
        self._win.show()

    def update_region(self, badge_rect=None) -> None:
        """Recompute and apply the click-through input region from the current cluster geometry."""
        compact = self._win.multitoon_tab._compact
        region = build_input_region(
            compact.card_body_paths(),
            compact.emblem_path(),
            self._host.content_transform(),
            badge_rect,
        )
        self._backend.apply_input_region(self._win, region)

    def set_scale_by_notches(self, notches: int) -> None:
        """Step the cluster scale by `notches` wheel notches, resize the window, and reapply region.

        Safe no-op when called in framed mode (self._host is None), so a stray
        scroll before entering transparent mode cannot raise AttributeError."""
        if self._host is None:
            return
        self._host.set_scale(step_scale(self._host.current_scale(), notches))
        self._win.resize(self._host.size())
        self.update_region()

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
