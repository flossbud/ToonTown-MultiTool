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

Confined mode (xcb only): each overlay is a MANAGED window kept directly
above its game window via WM_TRANSIENT_FOR (utils.x11_transient), so a
window overlapping the game covers the ghost instead of the ghost floating
over everything, and the glove is mask-clipped to the game rect at the
edges. Everywhere else (win32/cocoa/offscreen) the legacy always-on-top
float is unchanged. Kill switch: TTMT_GHOST_UNCONFINED=1.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QWidget

from utils import x11_transient
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


def _confinement_reason() -> str | None:
    """None when overlays can be confined to their game window (stacked
    directly above it via WM_TRANSIENT_FOR — probed on KWin Wayland
    2026-07-02); otherwise why not. xcb only: win32/cocoa keep the legacy
    always-on-top float and offscreen has no WM."""
    if os.environ.get("TTMT_GHOST_UNCONFINED") == "1":
        return "TTMT_GHOST_UNCONFINED=1"
    app = QGuiApplication.instance()
    name = (app.platformName() if app is not None else "") or ""
    if name.lower() != "xcb":
        return f"platform {name!r} (xcb only)"
    if not x11_transient.available():
        return "python-xlib/X display unavailable"
    return None


# The native->logical conversion lives in utils.screen_coords (shared with the
# overlay controller). Imported as the module-global name `_native_to_logical`
# so existing tests that import or monkeypatch it here keep working, and so the
# local `_emitted_to_logical` wrapper below honors that monkeypatch.
from utils.screen_coords import native_to_logical as _native_to_logical


def _emitted_to_logical(x, y, screens=None):
    """Map the service's emitted point into Qt's logical space. On darwin the
    service emits logical points (identity); elsewhere delegate to the module
    global `_native_to_logical` (so tests can monkeypatch it).

    This is a thin local wrapper (not `screen_coords.emitted_to_logical`) only so
    it keeps calling the module-global `_native_to_logical` that tests patch; keep
    its darwin branch in sync with `utils.screen_coords.emitted_to_logical`."""
    if sys.platform == "darwin":
        return (int(x), int(y))
    return _native_to_logical(x, y, screens)


def _win32_cloaked(hwnd: int) -> bool:
    """DWM-cloaked check (suspended UWP shells report IsWindowVisible=True
    while drawing nothing - they must not count as occluders). Best-effort."""
    try:
        import ctypes
        from ctypes import wintypes
        v = ctypes.c_int(0)
        r = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), 14,  # DWMWA_CLOAKED
            ctypes.byref(v), ctypes.sizeof(v))
        return r == 0 and v.value != 0
    except Exception:
        return False


def _win32_zorder_snapshot():
    """Visible top-level windows as (hwnd, (l, t, r, b), pid), TOP-FIRST in
    z-order (GetTopWindow + GW_HWNDNEXT walk - the documented z-order
    traversal). Rects are RAW physical px. Minimized and DWM-cloaked windows
    are dropped (bogus rects / painted nothing). None on failure (fail-open)."""
    try:
        import win32con
        import win32gui
        import win32process
        out = []
        h = win32gui.GetTopWindow(None)
        while h:
            try:
                if (win32gui.IsWindowVisible(h)
                        and not win32gui.IsIconic(h)
                        and not _win32_cloaked(h)):
                    rect = win32gui.GetWindowRect(h)
                    _tid, pid = win32process.GetWindowThreadProcessId(h)
                    out.append((int(h), tuple(rect), int(pid)))
            except Exception:
                pass
            h = win32gui.GetWindow(h, win32con.GW_HWNDNEXT)
        return out
    except Exception:
        return None


def _visible_glove_region(glove_rect, target_wid, snapshot, own_pid,
                          to_logical):
    """The glove pixels that should be visible, as a glove-LOCAL QRegion.

    Semantics match the X11 confined mode: the sprite exists only over its
    own game window's VISIBLE surface - clipped to the game's rect and
    carved by every FOREIGN window above the game in z-order (this process's
    windows never occlude: the float UI deliberately shows gloves).

    - ``glove_rect``: logical global QRect of the glove window.
    - ``snapshot``: `_win32_zorder_snapshot()` output (top-first).
    - ``to_logical(x, y)``: raw->logical corner conversion (injected).
    Returns None to FAIL OPEN (no snapshot), an EMPTY region when nothing of
    the glove should show (fully covered / game absent), else the region.
    """
    if snapshot is None:
        return None

    def _logical_rect(raw):
        left, top = to_logical(raw[0], raw[1])
        right, bottom = to_logical(raw[2], raw[3])
        return QRect(int(left), int(top),
                     int(right - left), int(bottom - top))

    occluders = []
    game_rect = None
    for hwnd, raw, pid in snapshot:
        if hwnd == target_wid:
            game_rect = _logical_rect(raw)
            break
        if pid == own_pid:
            continue
        occluders.append(_logical_rect(raw))
    if game_rect is None:
        return QRegion()  # game not on screen: nothing to hover over
    region = QRegion(glove_rect.intersected(game_rect))
    for occ in occluders:
        region -= QRegion(occ)
    return region.translated(-glove_rect.x(), -glove_rect.y())


class GhostCursorOverlay(QWidget):
    """One toon's glove: a 32x32 frameless, input-transparent toplevel. The
    EMPTY input shape (WindowTransparentForInput) is load-bearing: the
    click-sync source resolver's hit tests skip input-shape-empty windows on
    both platforms, so the overlay can never register as a foreign toplevel
    under the real pointer (spec: Resolver safety).

    Legacy (win32/cocoa/offscreen): always-on-top, WM-bypassed float.
    Confined (xcb): a MANAGED window whose WM_TRANSIENT_FOR is (re)asserted
    after every map — Qt rewrites the property on each show(), and only a
    managed window gets the WM's above-its-parent stacking constraint. The
    overlay stays MAPPED once shown (hides become opacity 0): unmapping
    would strip the property and flash the taskbar on every remap."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None,
                 confined: bool = False):
        if confined:
            flags = (Qt.Window | Qt.FramelessWindowHint
                     | Qt.WindowTransparentForInput
                     | Qt.WindowDoesNotAcceptFocus)
        else:
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
        self._confined = confined
        self._game_wid: int | None = None      # confinement target
        self._confined_this_map = False        # per-map assert latch
        self._pending_show_opacity: float | None = None
        self._confine_warned = False
        self._clip_rect: QRect | None = None
        self._occ_region: QRegion | None = None  # win32 occlusion mask
        # macOS NSWindow hardening state (no-op off cocoa).
        self._hardened = False
        self._harden_failed = False
        # windowOpacity is a toplevel property: animating it avoids
        # QGraphicsOpacityEffect, which conflicts with custom paintEvent.
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEndValue(0.0)
        if not confined:
            # Confined overlays stay mapped at opacity 0 instead (see class
            # docstring); the animation already ends there.
            self._fade.finished.connect(self.hide)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        if self._confined and not self._confined_this_map:
            # First paint after a map == the window is really mapped, so the
            # WM has managed it and the transient assert can land.
            QTimer.singleShot(0, self._confine)

    def show_at(self, x: int, y: int) -> None:
        if self._harden_failed:
            return   # macOS fail-closed: never show an un-hardenable ghost
        self._fade.stop()
        self.move(int(x) - HOTSPOT[0], int(y) - HOTSPOT[1])
        if self._confined and not self._confined_this_map:
            # Opacity-stage the map: invisible until _confine() has stacked
            # us above the game window, so the glove can never flash over an
            # occluding window in the pre-transient gap.
            self._pending_show_opacity = 1.0
            if not self.isVisible():
                self.setWindowOpacity(0.0)
        else:
            self.setWindowOpacity(1.0)
        if not self.isVisible():
            self.show()

    def set_game_window(self, wid: int | None) -> None:
        """Confinement target for this slot. On change while mapped the
        transient property is rewritten immediately — the WM tracks
        WM_TRANSIENT_FOR changes dynamically (probed on KWin)."""
        wid = int(wid) if wid else None
        if wid == self._game_wid:
            return
        self._game_wid = wid
        if (self._confined and wid is not None and self.isVisible()
                and self._confined_this_map):
            self._assert_confinement(wid)

    def set_visible_region(self, region: QRegion | None) -> None:
        """win32 occlusion mask, glove-LOCAL coords: clip the sprite to the
        part of its game window not covered by foreign windows, so it slides
        UNDER an occluder edge pixel-by-pixel instead of vanishing whole.
        None (fail-open) or a full-rect region clears the mask. The X11
        confined path uses clip_to instead; the two never run together
        (confined is xcb-only, this gate is win32-only)."""
        if region is None or region == QRegion(self.rect()):
            if self._occ_region is not None:
                self._occ_region = None
                self.clearMask()
            return
        if region == self._occ_region:
            return
        self._occ_region = QRegion(region)
        self.setMask(region)

    def clip_to(self, rect_logical: tuple[int, int, int, int] | None) -> None:
        """Clip the glove to the game window's rect (logical coords) so it
        never pokes past the game's edges; None restores the full shape.
        Cheap when nothing changes: the common fully-inside case clears any
        mask once and then skips the shape traffic."""
        if not self._confined:
            return
        if rect_logical is None:
            if self._clip_rect is not None:
                self._clip_rect = None
                self.clearMask()
            return
        local = QRect(*rect_logical).translated(-self.x(), -self.y())
        if local.contains(self.rect()):
            if self._clip_rect is not None:
                self._clip_rect = None
                self.clearMask()
            return
        if local != self._clip_rect:
            self._clip_rect = local
            self.setMask(QRegion(local.intersected(self.rect())))

    def _confine(self) -> None:
        """Post-map confinement (idempotent per map): WM_TRANSIENT_FOR ->
        the game window plus the skip-taskbar/switcher states, then lift the
        staged opacity."""
        if (not self._confined or self._confined_this_map
                or not self.isVisible()):
            return
        self._confined_this_map = True
        if self._game_wid is not None:
            self._assert_confinement(self._game_wid)
        op, self._pending_show_opacity = self._pending_show_opacity, None
        if op is not None and self._fade.state() != QPropertyAnimation.Running:
            self.setWindowOpacity(op)

    def _assert_confinement(self, wid: int) -> None:
        if not x11_transient.confine(int(self.winId()), wid):
            if not self._confine_warned:
                self._confine_warned = True
                print("[GhostCursors] transient confinement failed; "
                      "ghost may stack unconfined")

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._confined:
            # A real unmap strips WM_TRANSIENT_FOR (Qt rewrites it on the
            # next show), so the next map must re-stage and re-assert. Reset
            # HERE, not in showEvent: show_at() checks the latch before
            # show() fires showEvent, and a stale latch would skip the
            # opacity staging for the first post-remap frame.
            self._confined_this_map = False
            self._pending_show_opacity = None

    def showEvent(self, e):
        super().showEvent(e)
        if self._confined:
            # Fresh map: confinement must be (re)asserted. First paint is
            # the primary trigger (the window is provably mapped by then);
            # this timer is the fallback if no paint arrives promptly.
            QTimer.singleShot(120, self._confine)
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
        from utils.overlay.macos_backend import GHOST_WINDOW_LEVEL
        # Level 5 = above the cluster (3) AND the radial/panel band (4): a
        # ghost press can activate radial spokes, so the glove must be
        # visible over the open ring (live finding 2026-07-04 - gloves
        # vanished under the ring at the default floating level 3).
        ok, _reason = harden_overlay_window(self, level=GHOST_WINDOW_LEVEL)
        if ok:
            self._hardened = True
        elif not self._hardened:
            self._harden_failed = True
            self.hide_now()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        if self._confined and self.windowOpacity() == 0.0:
            return   # keep-mapped "hidden" state: nothing to fade
        self._fade.setStartValue(self.windowOpacity())
        self._fade.start()

    def hide_now(self) -> None:
        self._fade.stop()
        if self._confined and self.isVisible():
            # Stay mapped: unmapping strips WM_TRANSIENT_FOR (Qt rewrites it
            # each show) and blips the taskbar on every remap. Invisible +
            # input-transparent is equivalent to hidden.
            self._pending_show_opacity = None
            self.setWindowOpacity(0.0)
        else:
            self.hide()


class GhostCursorController(QObject):
    """Drives up to four lazily-created overlays from the service signals."""

    def __init__(self, service, settings_manager, parent=None,
                 slot_window_resolver=None, slot_rect_resolver=None):
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
        # slot -> (x, y, w, h) NATIVE game-window rect (the tab's
        # _cs_slot_rect closure); confined mode clips the glove to it.
        self._slot_rect_resolver = slot_rect_resolver
        self._focused_wid = ""
        # Glove echo over the float cards: the confined ghost windows stack
        # BELOW the dock-layer cluster, so the overlay paints its own echo of
        # each glove (clipped to visible card pixels). This controller is the
        # single owner of glove visibility (show/fade/focus-suppress/off), so
        # it mirrors every state change into the sink - the cluster
        # controller's ghost_echo_* methods (wired in main.py; None framed-only
        # setups). Unconfined floats already draw over the cards, so mirroring
        # is confined-mode only.
        self._echo_sink = None
        self._disabled_reason = self._platform_unsupported()
        if self._disabled_reason:
            print(f"[GhostCursors] disabled: {self._disabled_reason}")
        self._confine_reason = (self._disabled_reason
                                or _confinement_reason())
        self._confined = self._confine_reason is None
        # Windows occlusion gate: with no transient stacking on win32, the
        # unconfined float would draw gloves over EVERY window (file managers
        # included). Gate VISIBILITY instead: a glove shows only while the
        # top-level under its point is its own game window or a window of
        # THIS process (the float UI / main window). Probes are instance
        # attributes so tests can inject fakes; TTMT_GHOST_UNCONFINED=1 is
        # the shared kill switch (gloves float over everything, old behavior).
        self._occlusion_gated = (
            self._disabled_reason is None
            and not self._confined
            and sys.platform == "win32"
            and os.environ.get("TTMT_GHOST_UNCONFINED") != "1")
        self._zorder_probe = _win32_zorder_snapshot
        self._to_logical = _emitted_to_logical
        self._own_pid = os.getpid()
        self._last_logical: dict[int, tuple[int, int]] = {}
        self._occlusion_hidden: set[int] = set()
        self._occlusion_timer: QTimer | None = None
        if self._disabled_reason is None:
            # Running-code stamp: live validation starts by checking this.
            mode = ("confined-to-game (transient stacking)" if self._confined
                    else f"unconfined float ({self._confine_reason})")
            if self._occlusion_gated:
                mode += " + win32 occlusion gate"
            print(f"[GhostCursors] mode: {mode}")
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

    def set_echo_sink(self, sink) -> None:
        """Attach the overlay-side glove-echo sink (duck-typed: the cluster
        controller's ghost_echo_shown/fading/hidden/cleared). GUI thread."""
        self._echo_sink = sink
        if self._disabled_reason is None and sink is not None:
            # Running-code stamp: live validation of the card echo starts here.
            state = ("armed (confined mode)" if self._confined
                     else "inert (unconfined float draws over cards already)")
            print(f"[GhostCursors] card echo: {state}")

    def _echo_notify(self, method: str, *args) -> None:
        """Best-effort mirror of a glove state change to the echo sink.
        Cosmetic by contract: never raises into the ghost pipeline, and never
        runs unconfined (the legacy always-on-top float already renders over
        the cards, so an echo would double-draw)."""
        sink = self._echo_sink
        if sink is None or not self._confined:
            return
        try:
            getattr(sink, method)(*args)
        except Exception:
            pass

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
                self._echo_notify("ghost_echo_hidden", slot)
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
            lx, ly = _emitted_to_logical(x, y)
            if self._occlusion_gated:
                # Compute the mask BEFORE showing so a fully covered glove
                # never flashes for a frame over the occluder.
                self._last_logical[slot] = (lx, ly)
                region = self._compute_glove_region(slot, lx, ly)
                if region is not None and region.isEmpty():
                    self._occlusion_hidden.add(slot)
                    prev = self._overlays.get(slot)
                    if prev is not None:
                        prev.hide_now()
                    self._start_occlusion_sweep()
                    continue
                self._occlusion_hidden.discard(slot)
            else:
                region = None
            ov = self._overlay_for(slot)
            if ov is None:
                if self._disabled_reason is not None:
                    return  # asset failure just disabled the feature
                continue    # out-of-range slot: drop it, keep the batch
            if self._confined:
                # Target BEFORE show: a fresh map must confine to the
                # slot's current game window, not a stale one.
                ov.set_game_window(self._slot_wid_int(slot))
            ov.show_at(lx, ly)
            if self._occlusion_gated:
                ov.set_visible_region(region)
                self._start_occlusion_sweep()
            if self._confined:
                ov.clip_to(self._slot_rect_logical(slot))
                # Mirror the sprite onto the float cards (top-left = the same
                # hotspot-adjusted point show_at moved the window to).
                self._echo_notify("ghost_echo_shown", slot,
                                  lx - HOTSPOT[0], ly - HOTSPOT[1],
                                  ov._pixmap)
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

    def _slot_wid_int(self, slot: int) -> int | None:
        """The slot's game-window id as an int (resolvers hand out the
        decimal-string form), or None."""
        if self._slot_window_resolver is None:
            return None
        wid = self._slot_window_resolver(slot)
        try:
            return int(wid) if wid else None
        except (TypeError, ValueError):
            return None

    def _slot_rect_logical(self, slot: int):
        """The slot's game-window rect mapped into Qt logical space (both
        corners through the same conversion as the pointer), or None."""
        if self._slot_rect_resolver is None:
            return None
        g = self._slot_rect_resolver(slot)
        if g is None:
            return None
        x, y, w, h = g
        left, top = _emitted_to_logical(x, y)
        right, bottom = _emitted_to_logical(x + w, y + h)
        return (left, top, right - left, bottom - top)

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
            scaled, parent=parent if isinstance(parent, QWidget) else None,
            confined=self._confined)
        self._overlays[slot] = ov
        # winId() forces native-window creation: GUI thread only, done once
        # here so the capture thread never touches Qt internals.
        self._wid_cache = frozenset(
            str(int(o.winId())) for o in self._overlays.values())
        return ov

    # -- win32 occlusion gate ---------------------------------------------

    def _compute_glove_region(self, slot: int, lx: int, ly: int):
        """Visible region for the glove at logical point (lx, ly): its game
        window's surface minus foreign windows above it, in glove-local
        coords. None = fail open (no probe data / no resolver)."""
        target = self._slot_wid_int(slot)
        if target is None:
            return None
        snapshot = self._zorder_probe()
        glove = QRect(int(lx) - HOTSPOT[0], int(ly) - HOTSPOT[1],
                      CURSOR_SIZE, CURSOR_SIZE)
        return _visible_glove_region(glove, target, snapshot, self._own_pid,
                                     self._to_logical)

    def _start_occlusion_sweep(self) -> None:
        """Run the periodic re-mask while any glove is live: windows move
        OVER stationary gloves (carve/hide) and away again (restore) without
        any pointer traffic to tell us."""
        if not self._occlusion_gated:
            return
        t = self._occlusion_timer
        if t is None:
            t = QTimer(self)
            t.setInterval(100)
            t.timeout.connect(self._occlusion_sweep)
            self._occlusion_timer = t
        if not t.isActive():
            t.start()

    def _occlusion_sweep(self) -> None:
        any_live = False
        for slot, pos in list(self._last_logical.items()):
            ov = self._overlays.get(slot)
            if ov is None:
                continue
            region = self._compute_glove_region(slot, *pos)
            if region is not None and region.isEmpty():
                if slot not in self._occlusion_hidden:
                    self._occlusion_hidden.add(slot)
                    ov.hide_now()
                any_live = True   # keep sweeping: it may clear again
            else:
                if slot in self._occlusion_hidden:
                    self._occlusion_hidden.discard(slot)
                    if not self._suppressed_by_focus(slot):
                        ov.show_at(*pos)
                        self._restart_idle_timer(slot)
                if ov.isVisible():
                    ov.set_visible_region(region)
                    any_live = True
        if not any_live and self._occlusion_timer is not None:
            self._occlusion_timer.stop()

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
            self._echo_notify("ghost_echo_fading", slot, FADE_MS)

    def _hide_all(self) -> None:
        for t in self._timers.values():
            t.stop()
        for ov in self._overlays.values():
            ov.hide_now()
        if self._occlusion_timer is not None:
            self._occlusion_timer.stop()
        self._occlusion_hidden.clear()
        self._last_logical.clear()
        self._echo_notify("ghost_echo_cleared")
