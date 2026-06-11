"""Ghost cursors: per-toon glove overlays on click-synced windows.

Each window receiving synthetic click-sync input shows that toon's glove
cursor at the synthetic pointer position; the focused window (the one with
the real mouse) never does. This is the renderer for ClickSyncService's
ghost_pointer_event / ghost_clear signals.
Spec: docs/superpowers/specs/2026-06-11-click-sync-ghost-cursors-design.md.

Threading: service signals are emitted on capture/timer threads; Qt queued
delivery marshals them here. Everything in this module runs on the GUI
thread EXCEPT overlay_wids(), which the click-sync source resolver calls
from the capture thread — it returns a prebuilt frozenset (an atomic
reference read; the set is rebuilt on the GUI thread when an overlay is
created).
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from utils.settings_keys import GHOST_CURSORS_ENABLED

CURSOR_SIZE = 32   # px; matches TTR's own glove cursor
HOTSPOT = (1, 3)   # fingertip offset at 32 px (measured at (2, 12) in the
                   # 128 px asset; identical across all four gloves)
IDLE_HIDE_S = 1.5  # fade out this long after a slot's last event
FADE_MS = 150
SLOT_COUNT = 4
# "offscreen" is the test platform (widget geometry works there). Native
# Wayland is unsupported: clients cannot position global windows (the app
# defaults to xcb, so this only triggers under TTMT_USE_WAYLAND=1).
_SUPPORTED_PLATFORMS = ("xcb", "windows", "offscreen")


def _cursor_path(slot: int) -> str:
    """assets/cursors/toon{N}.png, repo-root or PyInstaller _MEIPASS
    relative (same convention as utils/cc_race_assets.py)."""
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
    )
    return os.path.join(base, "assets", "cursors", f"toon{slot + 1}.png")


class GhostCursorOverlay(QWidget):
    """One toon's glove: a 32x32 frameless, always-on-top, input-transparent
    toplevel. The EMPTY input shape (WindowTransparentForInput) is
    load-bearing: the click-sync source resolver's hit tests skip
    input-shape-empty windows on both platforms, so the overlay can never
    register as a foreign toplevel under the real pointer (spec: Resolver
    safety)."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.Tool | Qt.WindowTransparentForInput
                 | Qt.WindowDoesNotAcceptFocus)
        if sys.platform != "win32":
            flags |= Qt.X11BypassWindowManagerHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(CURSOR_SIZE, CURSOR_SIZE)
        self._pixmap = pixmap
        # windowOpacity is a toplevel property: animating it avoids
        # QGraphicsOpacityEffect, which conflicts with custom paintEvent.
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)

    def show_at(self, x: int, y: int) -> None:
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self.move(int(x) - HOTSPOT[0], int(y) - HOTSPOT[1])
        if not self.isVisible():
            self.show()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fade.setStartValue(self.windowOpacity())
        self._fade.start()

    def hide_now(self) -> None:
        self._fade.stop()
        self.hide()


class GhostCursorController(QObject):
    """Drives up to four lazily-created overlays from the service signals."""

    def __init__(self, service, settings_manager, parent=None):
        super().__init__(parent)
        self._enabled = True
        if settings_manager is not None:
            self._enabled = bool(
                settings_manager.get(GHOST_CURSORS_ENABLED, True))
            settings_manager.on_change(self._on_setting_changed)
        self._overlays: dict[int, GhostCursorOverlay] = {}
        self._timers: dict[int, QTimer] = {}
        self._wid_cache: frozenset[str] = frozenset()
        self._disabled_reason = self._platform_unsupported()
        if self._disabled_reason:
            print(f"[GhostCursors] disabled: {self._disabled_reason}")
        if service is not None:
            service.ghost_pointer_event.connect(self._on_pointer_event)
            service.ghost_clear.connect(self._on_clear)

    @staticmethod
    def _platform_unsupported(name: str | None = None) -> str | None:
        if name is None:
            app = QGuiApplication.instance()
            name = app.platformName() if app is not None else ""
        if (name or "").lower() in _SUPPORTED_PLATFORMS:
            return None
        return f"platform {name!r} cannot position global overlay windows"

    def overlay_wids(self) -> frozenset[str]:
        """Native window ids of created overlays, as decimal strings (the
        id format toplevel_at_point returns). Safe from any thread."""
        return self._wid_cache

    # -- signal handlers (GUI thread) -----------------------------------

    def _on_pointer_event(self, payload) -> None:
        if self._disabled_reason is not None or not self._enabled:
            return
        _kind, points = payload
        for slot, x, y in points:
            ov = self._overlay_for(slot)
            if ov is None:
                if self._disabled_reason is not None:
                    return  # asset failure just disabled the feature
                continue    # out-of-range slot: drop it, keep the batch
            ov.show_at(x, y)
            self._restart_idle_timer(slot)

    def _on_clear(self) -> None:
        self._hide_all()

    def _on_setting_changed(self, key, value) -> None:
        if key != GHOST_CURSORS_ENABLED:
            return
        self._enabled = bool(value)
        if not self._enabled:
            self._hide_all()

    # -- internals -------------------------------------------------------

    def _overlay_for(self, slot: int):
        ov = self._overlays.get(slot)
        if ov is not None:
            return ov
        if not 0 <= slot < SLOT_COUNT:
            return None
        path = _cursor_path(slot)
        pm = QPixmap(path)
        if pm.isNull():
            # Cosmetic feature: a broken asset must never affect click
            # sync itself. Log once, disable, move on.
            self._disabled_reason = f"cursor asset missing/unreadable: {path}"
            print(f"[GhostCursors] disabled: {self._disabled_reason}")
            self._hide_all()
            return None
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        scaled = pm.scaled(
            round(CURSOR_SIZE * dpr), round(CURSOR_SIZE * dpr),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        parent = self.parent()
        ov = GhostCursorOverlay(
            scaled, parent=parent if isinstance(parent, QWidget) else None)
        self._overlays[slot] = ov
        # winId() forces native-window creation: GUI thread only, done once
        # here so the capture thread never touches Qt internals.
        self._wid_cache = frozenset(
            str(int(o.winId())) for o in self._overlays.values())
        return ov

    def _restart_idle_timer(self, slot: int) -> None:
        t = self._timers.get(slot)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(int(IDLE_HIDE_S * 1000))
            t.timeout.connect(lambda s=slot: self._on_idle(s))
            self._timers[slot] = t
        t.start()

    def _on_idle(self, slot: int) -> None:
        ov = self._overlays.get(slot)
        if ov is not None:
            ov.fade_out()

    def _hide_all(self) -> None:
        for t in self._timers.values():
            t.stop()
        for ov in self._overlays.values():
            ov.hide_now()
