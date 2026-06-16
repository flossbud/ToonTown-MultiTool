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
# "offscreen" is the test platform (widget geometry works there). "cocoa" is
# macOS, where the overlay floats via a native NSWindow recipe (utils.macos_overlay;
# spike-proven 2026-06-15). Native Wayland is unsupported: clients cannot position
# global windows (the app defaults to xcb, so that only triggers under
# TTMT_USE_WAYLAND=1).
_SUPPORTED_PLATFORMS = ("xcb", "windows", "offscreen", "cocoa")


def _cursor_path(slot: int) -> str:
    """assets/cursors/toon{N}.png, repo-root or PyInstaller _MEIPASS
    relative (same convention as utils/cc_race_assets.py)."""
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
    )
    return os.path.join(base, "assets", "cursors", f"toon{slot + 1}.png")


def _native_to_logical(x, y, screens=None):
    """Map a native (physical) screen point into Qt's logical coordinate
    space. The service emits NATIVE pixels (capture, geometry, and
    injection all run in OS coordinates); QWidget.move() takes LOGICAL
    coordinates. Qt scales each screen around a fixed origin — the
    screen's top-left is numerically identical in both spaces and sizes
    divide by devicePixelRatio — so the containing screen is the one
    whose half-open native rect (origin, logical size * dpr) holds the
    point, and logical = origin + (native - origin) / dpr. At DPR 1 this
    is the identity, which is why the unit mismatch only ever showed on
    scaled-display Windows. A point inside no screen (transient geometry
    race) maps via the first screen rather than dropping the event."""
    if screens is None:
        screens = QGuiApplication.screens()
    target = None
    for s in screens:
        g = s.geometry()
        dpr = s.devicePixelRatio()
        if (g.x() <= x < g.x() + g.width() * dpr
                and g.y() <= y < g.y() + g.height() * dpr):
            target = s
            break
    if target is None:
        if not screens:
            return int(x), int(y)
        target = screens[0]
    g = target.geometry()
    dpr = target.devicePixelRatio()
    return (round(g.x() + (x - g.x()) / dpr),
            round(g.y() + (y - g.y()) / dpr))


def _emitted_to_logical(x, y, screens=None):
    """Map the service's emitted point into Qt's logical coordinate space.

    On macOS the service emits LOGICAL POINTS (all macOS geometry/capture/
    injection runs in points), and Qt's QWidget geometry is also points, so the
    mapping is the identity (negative multi-display coords preserved). Everywhere
    else the service emits physical pixels, so delegate to _native_to_logical
    (which divides by devicePixelRatio)."""
    if sys.platform == "darwin":
        return (int(x), int(y))
    return _native_to_logical(x, y, screens)


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
        # macOS NSWindow hardening state (no-op off cocoa).
        self._hardened = False
        self._harden_failed = False
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
        if self._harden_failed:
            return   # macOS fail-closed: never show an un-hardenable ghost
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self.move(int(x) - HOTSPOT[0], int(y) - HOTSPOT[1])
        if not self.isVisible():
            self.show()

    def showEvent(self, e):
        super().showEvent(e)
        # Gate on the REAL cocoa backend, not sys.platform: under the offscreen
        # QPA (tests on a Mac) winId() is not an NSView, so hardening must not
        # run (project_qt_winid_objc_offscreen_segv).
        if QGuiApplication.platformName() == "cocoa":
            # Harden after the native surface is realized (queued so .window()
            # is non-nil), matching the proven spike timing.
            QTimer.singleShot(0, self._harden_darwin)

    def event(self, e):
        from PySide6.QtCore import QEvent
        if (e.type() == QEvent.PlatformSurface
                and QGuiApplication.platformName() == "cocoa"):
            self._hardened = False               # surface (re)created
            QTimer.singleShot(0, self._harden_darwin)
        return super().event(e)

    def _harden_darwin(self) -> None:
        """Apply the floating-overlay NSWindow recipe (utils.macos_overlay). Fail
        CLOSED: a cosmetic ghost must never risk a misbehaving overlay, so if it
        has NEVER hardened and this attempt fails, hide and stay hidden."""
        from utils.macos_overlay import harden_overlay_window
        ok, _reason = harden_overlay_window(self)
        if ok:
            self._hardened = True
        elif not self._hardened:
            self._harden_failed = True
            self.hide_now()

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

    def __init__(self, service, settings_manager, parent=None,
                 slot_window_resolver=None):
        super().__init__(parent)
        self._enabled = True
        if settings_manager is not None:
            self._enabled = bool(
                settings_manager.get(GHOST_CURSORS_ENABLED, True))
            settings_manager.on_change(self._on_setting_changed)
        self._overlays: dict[int, GhostCursorOverlay] = {}
        self._timers: dict[int, QTimer] = {}
        self._wid_cache: frozenset[str] = frozenset()
        # Focus suppression (spec
        # 2026-06-12-ghost-cursor-focus-suppress-design.md): the focused
        # window never shows a ghost. Resolver maps slot -> wid (the tab's
        # _cs_slot_wid closure); without one, focus calls are inert.
        self._slot_window_resolver = slot_window_resolver
        self._focused_wid = ""
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

    def set_focused_window(self, wid: str | None) -> None:
        """Hide any ghost on the newly focused window and keep it
        suppressed while focus stays (the per-point guard in
        _on_pointer_event). GUI thread — queued from the WindowManager
        poll thread. None normalizes to "" (no active window)."""
        self._focused_wid = wid or ""
        if self._slot_window_resolver is None or not self._focused_wid:
            return
        for slot, ov in self._overlays.items():
            if self._slot_window_resolver(slot) == self._focused_wid:
                ov.hide_now()
                t = self._timers.get(slot)
                if t is not None:
                    t.stop()

    # -- signal handlers (GUI thread) -----------------------------------

    def _on_pointer_event(self, payload) -> None:
        if self._disabled_reason is not None or not self._enabled:
            return
        _kind, points = payload
        for slot, x, y in points:
            if self._suppressed_by_focus(slot):
                continue
            ov = self._overlay_for(slot)
            if ov is None:
                if self._disabled_reason is not None:
                    return  # asset failure just disabled the feature
                continue    # out-of-range slot: drop it, keep the batch
            ov.show_at(*_emitted_to_logical(x, y))
            self._restart_idle_timer(slot)

    def _on_clear(self) -> None:
        self._hide_all()

    def _on_setting_changed(self, key, value) -> None:
        if key != GHOST_CURSORS_ENABLED:
            return
        self._enabled = bool(value)
        if not self._enabled:
            self._hide_all()

    def _suppressed_by_focus(self, slot: int) -> bool:
        return (self._slot_window_resolver is not None
                and bool(self._focused_wid)
                and self._slot_window_resolver(slot) == self._focused_wid)

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
