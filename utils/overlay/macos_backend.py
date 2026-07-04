"""macOS overlay backend: NSWindow levels + the shared cursor-region arbiter.

The X11 backend punches input-only holes with the X Shape extension; macOS has
no input-shape API. Every mechanism below was probed live on the Mac (ledger:
docs/superpowers/specs/2026-07-03-macos-overlay-probe-ledger.md):

- ``NSWindow.setIgnoresMouseEvents_`` makes a whole window click-through and
  flips at runtime in ~0.2 ms (CP2: zero leaked clicks across fast boundary
  crossings at a 60 Hz poll; wheel events reach a hovered, never-activated
  overlay window).
- Clicking an interactive region of a plain ``NSWindow`` ACTIVATES the app
  (the game loses key). An ``NSPanel`` with
  ``NSWindowStyleMaskNonactivatingPanel`` takes clicks with ZERO activations
  (CP2-C: 58/58), so overlay surfaces are realized as panels on cocoa
  (``Qt.Tool``; see OverlaySurface) and this backend applies the mask pre-map.
- Distinct NSWindow LEVELS beat raise order (CP4), so the
  radial/panel-above-cluster invariant is levels: cluster at the floating
  level (3), radial/panel one above (4). Hardened windows stay above the
  frontmost, clicked game. Qt's own StaysOnTop level (8) is overridden.
- ``QWidget.setWindowOpacity`` blanks/restores exactly (CP3), so the content
  blanking / paint-staging machinery keeps its semantics unchanged.
- Fresh resize regions composite TRANSPARENT under a stalled event loop
  (CP6): the KWin black-band physics do not exist here; blanking is
  belt-and-suspenders.
- Background 16 ms timers are NOT App-Nap throttled (CP5: 62.5 Hz held), so
  the lazy arbiter poll needs no activity assertions.

Coordinate contract (differs from Windows, on purpose): macOS emits LOGICAL
points and Qt globals are logical, so ``apply_input_shape`` polygonizes at
dpr=1.0 and the arbiter ports (QCursor.pos / widget mapToGlobal) are logical
too - one consistent space, DPR-independent by construction (the identity law,
utils/screen_coords.py).

OWNERSHIP RULE: the arbiter is the ONLY writer of ``ignoresMouseEvents`` on
arbitrated surfaces (its applied-state cache is what makes flips cheap). The
level/behavior hardening here never touches that bit, and the post-map
re-asserts call ``arbiter.invalidate`` so a recreated native window (cocoa
PlatformSurface) cannot strand a stale cached state.

All PyObjC imports are lazy and every NSWindow touch is gated on the REAL
cocoa QPA via ``is_available()`` - never ``sys.platform`` alone (the
winId->objc offscreen segfault class). The constructor is pure (no winId, no
PyObjC) so the factory and tests can construct this class anywhere.
"""
from __future__ import annotations

import sys

from utils.overlay.backend import OverlayBackend, overlay_trace
from utils.overlay.cursor_arbiter import ARBITER_INTERVAL_MS, CursorRegionArbiter

# NSWindow levels, kept literal so pure tests run anywhere (CP1 readbacks:
# normal=0, floating=3, Qt StaysOnTop=8, status=25 on macOS 26.5).
CLUSTER_WINDOW_LEVEL = 3   # kCGFloatingWindowLevel
PANEL_WINDOW_LEVEL = 4     # floating+1: radial/panel strictly above (CP4)

# collectionBehavior bits: canJoinAllSpaces | stationary (the proven ghost
# recipe, utils/macos_overlay.py; CP1 confirmed it sticks on plain Qt windows).
_COLLECTION_BEHAVIOR = (1 << 0) | (1 << 4)

# NSWindowStyleMaskNonactivatingPanel - NSPanel-only (CP2-C).
_NONACTIVATING_PANEL_MASK = 1 << 7


class MacOSOverlayBackend(OverlayBackend):
    """OverlayBackend for macOS: NSWindow hardening + the cursor arbiter."""

    def __init__(self) -> None:
        self._arbiter = CursorRegionArbiter(
            cursor_pos=self._get_cursor_pos,
            window_origin=self._get_window_origin,
            apply_transparent=self._set_ignores_mouse,
        )
        self._timer = None  # lazy QTimer, GUI thread, runs only while needed
        self._pyobjc_ok: bool | None = None  # lazy import check, cached
        if self.is_available():
            overlay_trace("MacOSOverlayBackend: available (cursor arbiter ready)")

    # -- availability ----------------------------------------------------

    def is_available(self) -> bool:
        """darwin + the REAL cocoa QPA + PyObjC importable.

        The platformName gate (not sys.platform) is load-bearing: under the
        offscreen QPA winId() is not an NSView and wrapping it segfaults
        natively, so every gate downstream of is_available() must stay off.
        """
        if sys.platform != "darwin":
            return False
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app is None or QGuiApplication.platformName() != "cocoa":
                return False
        except Exception:
            return False
        if self._pyobjc_ok is None:
            try:
                import objc  # noqa: F401
                import AppKit  # noqa: F401
                self._pyobjc_ok = True
            except Exception:
                self._pyobjc_ok = False
        return self._pyobjc_ok

    def wants_taskbar_rep(self) -> bool:
        """The aligned-mirror representative is a KWin workaround. On macOS the
        APP owns its Dock icon and Cmd-Tab entry regardless of window state -
        per-window identity work does not exist here. (The controller stamps
        WIN_TASKBAR_IDENTITY when this returns False; that attr is win32
        ex-style data and is deliberately ignored by this backend, while its
        generic surface behaviors - spontaneous close -> app quit, minimize
        bounce - are sensible on cocoa too.)"""
        return False

    # -- NSWindow access (fresh resolve per call, never cached) -----------

    def _nswindow(self, window):
        """Resolve the widget's NSWindow fresh from winId(); None on failure.

        Only ever called behind is_available() (cocoa QPA), matching the
        proven macos_overlay recipe: never cache a wrapped objc ref across
        native surface recreation."""
        try:
            import objc
            view = objc.objc_object(c_void_p=int(window.winId()))
            return view.window()
        except Exception:
            return None

    # -- OS ports (injected into the arbiter; thin, no logic) ------------

    @staticmethod
    def _get_cursor_pos():
        """Logical global cursor point (matches the dpr=1.0 regions)."""
        try:
            from PySide6.QtGui import QCursor
            pos = QCursor.pos()
            return pos.x(), pos.y()
        except Exception:
            return None

    @staticmethod
    def _get_window_origin(key):
        """Logical global origin of the surface's client area; None evicts.

        The key IS the surface widget (opaque to the arbiter). A destroyed
        C++ object raises RuntimeError -> evict; a live but handle-less
        widget cannot receive input anyway -> evict (re-registered on the
        next apply_input_region)."""
        try:
            if key.windowHandle() is None:
                return None
            from PySide6.QtCore import QPoint
            p = key.mapToGlobal(QPoint(0, 0))
            return p.x(), p.y()
        except Exception:
            return None

    def _set_ignores_mouse(self, key, transparent: bool) -> None:
        win = self._nswindow(key)
        if win is None:
            return
        win.setIgnoresMouseEvents_(bool(transparent))

    # -- window hints -----------------------------------------------------

    def set_overlay_hints(self, window) -> None:
        return  # flags are set on the Qt side, matching the other backends

    def set_initial_state(self, window) -> None:
        """Pre-map NSWindow hardening: level per surface role + all-Spaces
        behavior + the nonactivating panel mask.

        Called while the native handle exists but the window is unmapped
        (prepare_initial_state), so the first mapped frame is already at the
        right level with no activation window. NEVER touches
        ignoresMouseEvents (arbiter ownership rule)."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        level = self._level_for(window)
        try:
            win.setLevel_(level)
            win.setCollectionBehavior_(_COLLECTION_BEHAVIOR)
        except Exception:
            return
        panel = self._apply_nonactivating(win)
        overlay_trace(
            f"macos set_initial_state: pre-map level={level} "
            f"behavior=allSpaces|stationary "
            f"{'nonactivating-panel' if panel else 'NOT a panel (activation possible)'}")

    @staticmethod
    def _level_for(window) -> int:
        """Surface role -> NSWindow level, keyed off the same WM_WINDOW_TYPE
        class attr the X11 backend reads (DOCK = cluster; the radial/panel
        subclasses override it with the OSD type). Levels enforce the
        radial/panel-above-cluster invariant immune to raise order (CP4)."""
        wtype = getattr(window, "WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK")
        if wtype == "_NET_WM_WINDOW_TYPE_DOCK":
            return CLUSTER_WINDOW_LEVEL
        return PANEL_WINDOW_LEVEL

    def _apply_nonactivating(self, win) -> bool:
        """styleMask |= NonactivatingPanel + never hide on app deactivate.
        NSPanel-only; returns whether the window is a panel."""
        try:
            import AppKit
            if not win.isKindOfClass_(AppKit.NSPanel):
                return False
            win.setStyleMask_(win.styleMask() | _NONACTIVATING_PANEL_MASK)
            win.setHidesOnDeactivate_(False)
            return True
        except Exception:
            return False

    def set_above(self, window) -> None:
        """Re-assert level+behavior per show (parity with the EWMH re-send).

        Also invalidates the arbiter's cached click-through state for this
        surface: a hide/show cycle can recreate the native NSWindow with the
        default (interactive) bit while the cache still holds the old state,
        and the cache-first apply would never correct it."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        try:
            win.setLevel_(self._level_for(window))
            win.setCollectionBehavior_(_COLLECTION_BEHAVIOR)
        except Exception:
            pass
        self._arbiter.invalidate(window)

    def set_non_activating(self, window) -> None:
        """Re-assert the nonactivating panel bits (idempotent, per show)."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        self._apply_nonactivating(win)

    def set_rep_initial_state(self, window) -> None:
        """No-op: the representative is never constructed on macOS
        (wants_taskbar_rep() is False; the Dock identity is app-level)."""
        overlay_trace("macos set_rep_initial_state: no-op (rep unused on macOS)")

    def set_skip_close_animation(self, window) -> None:
        return  # no KWin close animation to skip

    def set_window_opacity(self, window, opacity: float) -> None:
        """Whole-window opacity via Qt (NSWindow alphaValue underneath).

        Probe CP3: pre-map setWindowOpacity(0) keeps the mapped window fully
        invisible and 1.0 restores it pixel-identically, so the content
        blanking / paint-staging machinery keeps its semantics on macOS."""
        try:
            window.setWindowOpacity(max(0.0, min(1.0, float(opacity))))
        except Exception:
            pass

    # -- input shape (the actual macOS work) ------------------------------

    def apply_input_shape(self, window, path, dpr: float) -> None:
        """Logical-coord QPainterPath -> LOGICAL region -> arbiter entry.

        Deliberately ignores the caller's dpr: on macOS the arbiter ports
        (QCursor.pos / mapToGlobal) are logical points, so the region must be
        polygonized at 1.0 to share their space (the identity law; CP2 ran
        this exact contract live). The caller keeps passing the real dpr -
        the X11/win32 backends need it - and this backend owns the divergence."""
        if not self.is_available():
            return
        from utils.overlay.region import device_input_region
        self.apply_input_region(window, device_input_region(path, 1.0))

    def apply_input_region(self, window, region) -> None:
        if not self.is_available() or region is None:
            return
        try:
            window.winId()  # no-op if realized; the port needs a live handle
        except Exception:
            return
        self._arbiter.set_region(window, region)
        self._update_timer()

    def clear_input_region(self, window) -> None:
        if not self.is_available():
            return
        self._arbiter.clear(window)
        self._update_timer()

    # -- arbiter timer -----------------------------------------------------

    def _update_timer(self) -> None:
        """Run the 60 Hz poll only while some region actually needs it."""
        need = self._arbiter.needs_polling
        if need and self._timer is None:
            from PySide6.QtCore import QTimer
            t = QTimer()
            t.setInterval(ARBITER_INTERVAL_MS)
            t.timeout.connect(self._on_tick)
            t.start()
            self._timer = t
            overlay_trace("macos arbiter: 60 Hz cursor poll STARTED")
        elif not need and self._timer is not None:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None
            overlay_trace("macos arbiter: cursor poll stopped (no dynamic regions)")

    def _on_tick(self) -> None:
        self._arbiter.tick()
        # Entries can self-evict on a dead window; stop polling when drained.
        if not self._arbiter.needs_polling:
            self._update_timer()
