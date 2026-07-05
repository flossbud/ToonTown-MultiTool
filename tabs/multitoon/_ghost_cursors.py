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
import threading
import time

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


# CGWindowListCopyWindowInfo is a WINDOW-SERVER ROUND TRIP: ~1.5ms idle with
# 40 windows on-screen, SPIKING to 12-16ms under live game load (measured
# both ways). Two laws came out of the live smoothness saga (CP15/CP16):
# probe cost must be bounded by a TTL, and the FRAME PATH must never pay the
# round trip at all - a synchronous refresh every TTL hitched one frame by
# 12-16ms ~20x/second. So the cache is STALE-WHILE-REVALIDATE: an expired
# read serves the stale snapshot immediately and kicks ONE background
# refresh; only the refresher thread ever talks to the window server. The
# mask basis is at most a refresh behind (~the 100ms occlusion sweep already
# accepts that staleness for moving occluders). win32's user-mode z-order
# walk needs none of this.
_DARWIN_SNAP_TTL_S = 0.05
_darwin_snap_cache = {"t": -1.0, "snap": None}
_darwin_snap_lock = threading.Lock()      # guards the refreshing flag
_darwin_snap_refreshing = False


def _reset_darwin_snapshot_cache() -> None:
    """Test hook (mirrors macos_discovery._reset_enum_cache)."""
    global _darwin_snap_refreshing
    with _darwin_snap_lock:
        _darwin_snap_refreshing = False
    _darwin_snap_cache["t"] = -1.0
    _darwin_snap_cache["snap"] = None


def _refresh_darwin_snapshot():
    """Synchronous probe + store (refresher thread; tests call it directly).
    Visible on-screen windows as (window_number, (l, t, r, b), pid),
    TOP-FIRST (CGWindowListCopyWindowInfo with OnScreenOnly returns windows
    front-to-back). Rects are GLOBAL points - identity with Qt logical space
    on this backend (dpr-1.0 logical regions, D2), so the shared region math
    runs unconverted. Reads ONLY kCGWindowNumber / kCGWindowOwnerPID /
    kCGWindowBounds: kCGWindowName can demand the Screen Recording TCC
    prompt and must never be touched here. On failure the previous snapshot
    stays in place (a transient window-server error must not blank the mask
    basis); returns the stored snapshot or None."""
    try:
        from utils.macos_discovery import _raw_window_info
        out = []
        for info in _raw_window_info():
            try:
                num = info.get("kCGWindowNumber")
                pid = info.get("kCGWindowOwnerPID")
                b = info.get("kCGWindowBounds")
                if num is None or pid is None or not b:
                    continue
                x, y = float(b.get("X", 0)), float(b.get("Y", 0))
                w, h = float(b.get("Width", 0)), float(b.get("Height", 0))
                if w <= 0 or h <= 0:
                    continue
                out.append((int(num),
                            (int(x), int(y), int(x + w), int(y + h)),
                            int(pid)))
            except Exception:
                continue
    except Exception:
        return _darwin_snap_cache["snap"]
    _darwin_snap_cache["snap"] = out
    _darwin_snap_cache["t"] = time.monotonic()
    return out


def _kick_darwin_snapshot_refresh() -> None:
    """Spawn at most ONE background refresh (tests monkeypatch this to run
    synchronously). Daemon: a refresh in flight at app exit is abandonable."""
    global _darwin_snap_refreshing
    with _darwin_snap_lock:
        if _darwin_snap_refreshing:
            return
        _darwin_snap_refreshing = True

    def _run():
        global _darwin_snap_refreshing
        try:
            _refresh_darwin_snapshot()
        finally:
            with _darwin_snap_lock:
                _darwin_snap_refreshing = False

    threading.Thread(target=_run, name="ghost-snapshot-refresh",
                     daemon=True).start()


def _darwin_zorder_snapshot():
    """Frame-path read: NEVER blocks on the window server. Fresh cache ->
    serve it; expired -> kick a background refresh and serve the STALE
    snapshot (None only before the first refresh ever lands = fail-open,
    gloves render unmasked for those first frames)."""
    now = time.monotonic()
    if now - _darwin_snap_cache["t"] >= _DARWIN_SNAP_TTL_S:
        _kick_darwin_snapshot_refresh()
    return _darwin_snap_cache["snap"]


def _scan_region_inputs(target_wid, snapshot, own_pid, to_logical):
    """One pass over the z-order snapshot -> (game_rect, occluder_rects) in
    logical coords, or None when the game is not on screen. Split out of
    _visible_glove_region so the per-frame path can reuse a scan per
    SNAPSHOT instead of re-walking every window per glove move (at 240Hz
    frame cadence the full-snapshot walk was measurable Python work).

    ``own_pid``: an int or a CONTAINER of ints whose windows never occlude
    (the float UI deliberately shows gloves over its own surfaces). The
    container form exists for the helper-process renderer, where "own"
    means the whole TTMT process family - the renderer AND the app that
    spawned it (the app's float cards carved gloves to nothing when only
    the renderer's pid was exempt: live 3-toon regression 2026-07-04)."""
    own_pids = {own_pid} if isinstance(own_pid, int) else set(own_pid)

    def _logical_rect(raw):
        left, top = to_logical(raw[0], raw[1])
        right, bottom = to_logical(raw[2], raw[3])
        return QRect(int(left), int(top),
                     int(right - left), int(bottom - top))

    occluders = []
    for hwnd, raw, pid in snapshot:
        if hwnd == target_wid:
            return _logical_rect(raw), occluders
        if pid in own_pids:
            continue
        occluders.append(_logical_rect(raw))
    return None


def _region_from_inputs(glove_rect, inputs):
    """(game_rect, occluders) + glove rect -> glove-LOCAL visible QRegion.
    EMPTY region when nothing of the glove should show."""
    if inputs is None:
        return QRegion()  # game not on screen: nothing to hover over
    game_rect, occluders = inputs
    region = QRegion(glove_rect.intersected(game_rect))
    for occ in occluders:
        # Only intersecting occluders change the region; skipping the rest
        # keeps the common fully-visible case allocation-light.
        if occ.intersects(glove_rect):
            region -= QRegion(occ)
    return region.translated(-glove_rect.x(), -glove_rect.y())


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
    return _region_from_inputs(
        glove_rect,
        _scan_region_inputs(target_wid, snapshot, own_pid, to_logical))


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
        """Occlusion-gate mask (win32 + darwin), glove-LOCAL coords: clip the
        sprite to the part of its game window not covered by foreign windows,
        so it slides UNDER an occluder edge pixel-by-pixel instead of
        vanishing whole. None (fail-open) or a full-rect region clears the
        mask. The X11 confined path uses clip_to instead; the two never run
        together (confined is xcb-only, this gate is win32/darwin-only)."""
        if region is None or region == QRegion(self.rect()):
            if self._occ_region is not None:
                self._occ_region = None
                self.clearMask()
            return
        if region.isEmpty():
            # CP8 landmine: setMask(QRegion()) is a NO-OP ("no mask") on
            # cocoa, so an empty mask would show the WHOLE glove instead of
            # nothing. Fully-carved is the controller's explicit-hide case;
            # enforce it here too so no call site can ever trip the trap.
            self._occ_region = None
            self.clearMask()
            self.hide_now()
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
        # Occlusion gate (win32 + darwin): with no transient stacking on
        # these backends, the unconfined float would draw gloves over EVERY
        # window (file managers included) - on cocoa the CP14 fix even lifts
        # gloves to level 5, above the radial band. Gate VISIBILITY instead:
        # clip each glove to its game window's visible surface ((glove ∩
        # game) minus foreign windows above the game; own-pid windows never
        # occlude - the float UI deliberately shows gloves over the cards
        # and the ring). Probes are instance attributes so tests can inject
        # fakes; TTMT_GHOST_UNCONFINED=1 is the shared kill switch (gloves
        # float over everything, old behavior).
        self._occlusion_gated = (
            self._disabled_reason is None
            and not self._confined
            and sys.platform in ("win32", "darwin")
            and os.environ.get("TTMT_GHOST_UNCONFINED") != "1")
        self._zorder_probe = (_darwin_zorder_snapshot
                              if sys.platform == "darwin"
                              else _win32_zorder_snapshot)
        self._to_logical = _emitted_to_logical
        self._own_pid = os.getpid()
        self._last_logical: dict[int, tuple[int, int]] = {}
        self._occlusion_hidden: set[int] = set()
        self._occlusion_timer: QTimer | None = None
        # Frame-paced rendering (live finding 2026-07-04): the service emits
        # a ghost point per CAPTURED MOTION EVENT (up to the mouse's polling
        # rate, 1000Hz on gaming mice), and running the full render per emit
        # kept the GUI thread saturated even after the snapshot probe was
        # cached - gloves stuttered instead of gliding. A real cursor is
        # smooth because the display samples only the LATEST position once
        # per frame; same here: _on_pointer_event just stores the newest
        # point per slot, and the frame driver renders dirty slots at frame
        # cadence. The FIRST event after idle renders synchronously (a press
        # shows its glove instantly); backlog is impossible by construction
        # at any polling rate. 4ms ~ 250fps ceiling (covers the 240Hz
        # display); the driver stops itself when no samples arrive.
        self._pending_points: dict[int, tuple[int, int]] = {}
        self._frame_timer: QTimer | None = None
        # Opt-in render-side rate diagnostics (TTMT_CLICK_DIAG=1, pairs with
        # the click_sync_service capture-side print): emits/points arriving
        # from the service vs frames actually rendered, plus the achieved
        # inter-tick gap while streaming. Tells "is the source starving us
        # (emits/s low) or is the GUI thread late (renders/s low, gaps big)".
        self._diag = None
        if os.environ.get("TTMT_CLICK_DIAG"):
            self._diag = {"t0": time.monotonic(), "emits": 0, "points": 0,
                          "renders": 0, "last_tick": 0.0,
                          "gap_s": 0.0, "gap_max": 0.0, "gaps": 0,
                          "move_s": 0.0, "move_max": 0.0,
                          "region_s": 0.0, "region_max": 0.0,
                          "ref_last": 0.0, "ref_s": 0.0,
                          "ref_max": 0.0, "refs": 0}
            # Reference jitter probe: a bare 4ms timer doing NOTHING but
            # timing itself. If ITS gaps match the frame driver's, the
            # event loop/GIL is the cadence floor - the ghost work is not
            # what is late.
            ref = QTimer(self)
            ref.setTimerType(Qt.PreciseTimer)
            ref.setInterval(4)

            def _ref_tick():
                d = self._diag
                now = time.monotonic()
                if d["ref_last"]:
                    gap = now - d["ref_last"]
                    d["ref_s"] += gap
                    d["refs"] += 1
                    if gap > d["ref_max"]:
                        d["ref_max"] = gap
                d["ref_last"] = now

            ref.timeout.connect(_ref_tick)
            ref.start()
        # Per-target (game_rect, occluders-above) derived from the CURRENT
        # z-order snapshot, keyed by snapshot identity: the TTL-cached darwin
        # snapshot is the same object across a cache window, so the scan of
        # every on-screen window runs once per snapshot instead of once per
        # rendered frame per glove. {target: (snap_id, inputs)}
        self._region_inputs_cache: dict[int, tuple[int, object]] = {}
        # Helper-process renderer (ledger CP17): the app's single Qt loop +
        # GIL floor in-process glove cadence at ~50-60Hz under live load (a
        # bare 4ms reference timer gapped 17-22ms, 1:1 with the frame
        # driver). The renderer is a separate process whose loop only draws
        # gloves; POSITIONS reach it from the CAPTURE THREAD over its stdin
        # pipe (Qt.DirectConnection below runs _feed_renderer on the
        # emitting thread), bypassing this process's GUI loop entirely.
        # Falls back to in-process rendering if the spawn fails or the
        # renderer dies mid-run. Kill switch: TTMT_GHOST_RENDERER=0.
        self._renderer = None
        self._service = service
        if (self._disabled_reason is None and not self._confined
                and sys.platform == "darwin" and service is not None
                and os.environ.get("TTMT_GHOST_RENDERER") != "0"
                and QGuiApplication.platformName() == "cocoa"):
            # Real-cocoa gate: under the offscreen QPA (tests) a helper
            # process adds nothing and every suite would fork one.
            try:
                from utils.ghost_renderer_client import GhostRendererClient
                client = GhostRendererClient()
                if client.start():
                    self._renderer = client
            except Exception as e:                     # noqa: BLE001
                print(f"[GhostCursors] renderer client unavailable: {e}")
        if self._disabled_reason is None:
            # Running-code stamp: live validation starts by checking this.
            mode = ("confined-to-game (transient stacking)" if self._confined
                    else f"unconfined float ({self._confine_reason})")
            if self._occlusion_gated:
                probe = ("CGWindowList" if sys.platform == "darwin"
                         else "win32")
                mode += f" + {probe} occlusion gate"
            if self._renderer is not None:
                mode += f" + helper renderer pid={self._renderer.pid}"
            print(f"[GhostCursors] mode: {mode}")
        if service is not None:
            service.ghost_pointer_event.connect(self._on_pointer_event)
            service.ghost_clear.connect(self._on_clear)
            if self._renderer is not None:
                # DIRECT: runs on the service's emitting (capture) thread.
                service.ghost_pointer_event.connect(
                    self._feed_renderer, Qt.DirectConnection)

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
        client = self._renderer
        if client is not None:
            client.send_focus(self._focused_wid or None)
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
        """Sampler half of the frame-paced pipeline: record the newest point
        per slot (display-only - the event kind never mattered here) and let
        the frame driver render it. Near-free, so a 1000Hz-polling mouse
        costs the GUI thread nothing but dict stores."""
        if self._disabled_reason is not None or not self._enabled:
            return
        _kind, points = payload
        d = self._diag
        if d is not None:
            d["emits"] += 1
            d["points"] += len(points)
        if self._renderer is not None:
            return   # the helper process renders; positions ride _feed_renderer
        for slot, x, y in points:
            self._pending_points[slot] = (int(x), int(y))
        if self._pending_points:
            self._drive_frames()

    def _feed_renderer(self, payload) -> None:
        """CAPTURE-THREAD feed (Qt.DirectConnection on the service signal):
        encode positions + wids and write them to the renderer's stdin
        without ever blocking (the client drops on a full pipe). A dead
        renderer flips the controller back to in-process rendering - the
        queued _on_pointer_event path resumes on the very next event."""
        client = self._renderer
        if (client is None or self._disabled_reason is not None
                or not self._enabled):
            return
        _kind, points = payload
        resolver = self._slot_window_resolver
        batch = []
        for slot, x, y in points:
            wid = resolver(slot) if resolver is not None else None
            batch.append((slot, int(x), int(y), wid))
        if not batch:
            return
        # The service stashes the batch's EVENT time right before the emit
        # on THIS thread (DirectConnection runs inline during the emit), so
        # the read is race-free. It rides every P line for the renderer's
        # dejitter timeline.
        t_ms = getattr(self._service, "ghost_event_ms", None)
        if not client.send_positions(batch, t_ms) or not client.alive():
            self._renderer = None
            print("[GhostCursors] renderer died - in-process rendering "
                  "resumes")

    def _drive_frames(self) -> None:
        """Render pending samples NOW if the driver was idle (instant first
        paint), then keep the frame timer running for whatever streams in."""
        t = self._frame_timer
        if t is None:
            t = QTimer(self)
            t.setTimerType(Qt.PreciseTimer)
            t.setInterval(4)   # ~250fps ceiling; stops itself when idle
            t.timeout.connect(self._frame_tick)
            self._frame_timer = t
        if not t.isActive():
            self._frame_tick()
            t.start()   # next tick with nothing pending stops it again

    def _frame_tick(self) -> None:
        pending = self._pending_points
        d = self._diag
        if not pending:
            if self._frame_timer is not None:
                self._frame_timer.stop()
            if d is not None:
                d["last_tick"] = 0.0   # stream ended: next gap starts fresh
            return
        self._pending_points = {}
        if d is not None:
            now = time.monotonic()
            if d["last_tick"]:
                gap = now - d["last_tick"]
                d["gap_s"] += gap
                d["gaps"] += 1
                if gap > d["gap_max"]:
                    d["gap_max"] = gap
            d["last_tick"] = now
            d["renders"] += len(pending)
            elapsed = now - d["t0"]
            if elapsed >= 1.0:
                gap_mean = (d["gap_s"] / d["gaps"] * 1000) if d["gaps"] else 0.0
                ref_mean = (d["ref_s"] / d["refs"] * 1000) if d["refs"] else 0.0
                n = d["renders"] or 1
                print(f"[ghost_perf] emits={d['emits']/elapsed:.0f}/s "
                      f"points={d['points']/elapsed:.0f}/s "
                      f"renders={d['renders']/elapsed:.0f}/s | tick gap "
                      f"mean={gap_mean:.1f}ms max={d['gap_max']*1000:.1f}ms | "
                      f"move mean={d['move_s']/n*1000:.2f}ms "
                      f"max={d['move_max']*1000:.1f}ms | region "
                      f"mean={d['region_s']/n*1000:.2f}ms "
                      f"max={d['region_max']*1000:.1f}ms | ref gap "
                      f"mean={ref_mean:.1f}ms max={d['ref_max']*1000:.1f}ms",
                      flush=True)
                d.update(t0=now, emits=0, points=0, renders=0,
                         gap_s=0.0, gap_max=0.0, gaps=0,
                         move_s=0.0, move_max=0.0,
                         region_s=0.0, region_max=0.0,
                         ref_s=0.0, ref_max=0.0, refs=0)
        for slot, (x, y) in pending.items():
            self._render_point(slot, x, y)

    def _render_point(self, slot: int, x: int, y: int) -> None:
        if self._disabled_reason is not None or not self._enabled:
            return
        if self._suppressed_by_focus(slot):
            return
        lx, ly = _emitted_to_logical(x, y)
        d = self._diag
        if self._occlusion_gated:
            # Compute the mask BEFORE showing so a fully covered glove
            # never flashes for a frame over the occluder.
            self._last_logical[slot] = (lx, ly)
            if d is not None:
                _t0 = time.monotonic()
                region = self._compute_glove_region(slot, lx, ly)
                _dt = time.monotonic() - _t0
                d["region_s"] += _dt
                if _dt > d["region_max"]:
                    d["region_max"] = _dt
            else:
                region = self._compute_glove_region(slot, lx, ly)
            if region is not None and region.isEmpty():
                self._occlusion_hidden.add(slot)
                prev = self._overlays.get(slot)
                if prev is not None:
                    prev.hide_now()
                self._start_occlusion_sweep()
                return
            self._occlusion_hidden.discard(slot)
        else:
            region = None
        ov = self._overlay_for(slot)
        if ov is None:
            return      # asset failure disabled the feature / bad slot
        if self._confined:
            # Target BEFORE show: a fresh map must confine to the
            # slot's current game window, not a stale one.
            ov.set_game_window(self._slot_wid_int(slot))
        if d is not None:
            _t0 = time.monotonic()
            ov.show_at(lx, ly)
            _dt = time.monotonic() - _t0
            d["move_s"] += _dt
            if _dt > d["move_max"]:
                d["move_max"] = _dt
        else:
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
        coords. None = fail open (no probe data / no resolver).

        The snapshot scan is cached per (target, snapshot IDENTITY): the
        TTL-cached darwin snapshot is the same object across a cache window,
        so at frame cadence the full window-list walk runs once per snapshot
        refresh, not once per rendered frame per glove. Identity is held by
        strong reference (never id()) so a recycled allocation can never
        false-hit."""
        target = self._slot_wid_int(slot)
        if target is None:
            return None
        snapshot = self._zorder_probe()
        if snapshot is None:
            return None
        glove = QRect(int(lx) - HOTSPOT[0], int(ly) - HOTSPOT[1],
                      CURSOR_SIZE, CURSOR_SIZE)
        cached = self._region_inputs_cache.get(target)
        if cached is not None and cached[0] is snapshot:
            inputs = cached[1]
        else:
            inputs = _scan_region_inputs(target, snapshot, self._own_pid,
                                         self._to_logical)
            self._region_inputs_cache[target] = (snapshot, inputs)
        return _region_from_inputs(glove, inputs)

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
        client = self._renderer
        if client is not None:
            client.send_clear()
        for t in self._timers.values():
            t.stop()
        for ov in self._overlays.values():
            ov.hide_now()
        if self._occlusion_timer is not None:
            self._occlusion_timer.stop()
        if self._frame_timer is not None:
            self._frame_timer.stop()
        self._pending_points.clear()
        self._occlusion_hidden.clear()
        self._last_logical.clear()
        self._echo_notify("ghost_echo_cleared")
