"""Win32 overlay backend: dynamic click-through via a cursor-region arbiter.

The X11 backend punches input-only holes with the X Shape extension; Windows
has no input-shape API. The mechanisms below were probed live on the winbox
(ledger: docs/superpowers/specs/2026-07-03-win32-overlay-probe-ledger.md):

- ``WS_EX_TRANSPARENT | WS_EX_LAYERED`` makes a whole window click-through,
  can be flipped at runtime with ``SetWindowLong`` + ``SetWindowPos``
  (FRAMECHANGED), and takes effect in ~1 ms (P2a). A 60 Hz cursor arbiter
  driving that flip caught 10/10 instant-click races at ~2000 px/s cursor
  speed in both directions (P2b) - faster than any human approach.
- DWM already hit-tests FULLY TRANSPARENT pixels of a layered (translucent)
  Qt window through to the window beneath (P2a case D), so the arbiter only
  matters where the surface PAINTS opaque content the input shape excludes
  (card bodies vs their controls).
- Wheel events reach a hovered, never-activated overlay window (P2b B5),
  which is what emblem scroll-zoom needs.

Region semantics mirror X Shape exactly:

- never shaped        -> fully interactive (Qt default; no arbiter entry)
- empty region        -> fully click-through (static ``WS_EX_TRANSPARENT``)
- non-empty region    -> arbitrated per cursor position at 60 Hz
- clear_input_region  -> back to fully interactive

Windows-only concerns the X11 backend never had (both probed, P1/P5):

- A parentless ``Qt.Window`` top-level gets a TASKBAR BUTTON on Windows.
  ``set_initial_state`` adds ``WS_EX_TOOLWINDOW`` pre-map to suppress it,
  unless the surface opts into taskbar identity via a
  ``WIN_TASKBAR_IDENTITY = True`` class attribute, which gets
  ``WS_EX_APPWINDOW`` instead (NOACTIVATE alone would hide it from the
  taskbar; NOACTIVATE+APPWINDOW is listed - the float-mode cluster entry).
- ``Qt.WindowDoesNotAcceptFocus`` does NOT set ``WS_EX_NOACTIVATE`` (Qt
  handles activation internally), so it is set explicitly here.

The taskbar REPRESENTATIVE (the KWin aligned-mirror workaround) is not used
on Windows at all: ``wants_taskbar_rep()`` is False and the cluster window
itself carries the taskbar identity instead.

All methods run on the GUI thread (same contract as the X11 backend). Every
OS access in the arbiter core is injected so the flip logic is unit-testable
off-Windows.
"""
from __future__ import annotations

import sys

from utils.overlay.backend import OverlayBackend, overlay_trace
# The arbiter core is platform-neutral and shared with the macOS backend.
# Re-exported here so existing imports (tests, callers) keep working.
from utils.overlay.cursor_arbiter import (  # noqa: F401 (re-export)
    ARBITER_INTERVAL_MS,
    CursorRegionArbiter,
)

try:  # guarded so the module imports everywhere (self-check sweep, Linux CI)
    import win32con
    import win32gui
except ImportError:
    win32con = win32gui = None

# Ex-style bits (kept literal so the pure arbiter tests run off-Windows).
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


class Win32OverlayBackend(OverlayBackend):
    """OverlayBackend for Windows: ex-style hints + the cursor arbiter."""

    def __init__(self) -> None:
        self._arbiter = CursorRegionArbiter(
            cursor_pos=self._get_cursor_pos,
            window_origin=self._get_window_origin,
            apply_transparent=self._set_transparent,
        )
        self._timer = None  # lazy QTimer, GUI thread, runs only while needed
        if self.is_available():
            overlay_trace("Win32OverlayBackend: available (cursor arbiter ready)")

    # -- availability ----------------------------------------------------

    def is_available(self) -> bool:
        return sys.platform == "win32" and win32gui is not None

    def wants_taskbar_rep(self) -> bool:
        """The aligned-mirror representative is a KWin workaround; on Windows
        the cluster window itself is taskbar-listed (WIN_TASKBAR_IDENTITY)."""
        return False

    # -- OS ports (injected into the arbiter; thin, no logic) ------------

    @staticmethod
    def _get_cursor_pos():
        try:
            return win32gui.GetCursorPos()
        except Exception:
            return None

    @staticmethod
    def _get_window_origin(hwnd):
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            rect = win32gui.GetWindowRect(hwnd)
            return rect[0], rect[1]
        except Exception:
            return None

    def _set_transparent(self, hwnd, transparent: bool) -> None:
        # TRANSPARENT needs LAYERED for cross-process pass-through; Qt sets
        # LAYERED on translucent windows already, adding it again is a no-op.
        if transparent:
            self._flip_ex(hwnd, add=WS_EX_LAYERED | WS_EX_TRANSPARENT)
        else:
            self._flip_ex(hwnd, remove=WS_EX_TRANSPARENT)

    @staticmethod
    def _flip_ex(hwnd, add: int = 0, remove: int = 0) -> None:
        try:
            if not win32gui.IsWindow(hwnd):
                return
            v = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            new = (v | add) & ~remove
            if new == v:
                return
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new)
            win32gui.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
                | win32con.SWP_FRAMECHANGED)
        except Exception:
            pass  # never crash the UI on a style failure (X-backend parity)

    # -- window hints -----------------------------------------------------

    def set_overlay_hints(self, window) -> None:
        return  # flags are set on the Qt side, matching the X11 backend

    def set_initial_state(self, window) -> None:
        """Pre-map ex-styles: NOACTIVATE always; TOOLWINDOW (skip taskbar)
        unless the surface claims taskbar identity, then APPWINDOW (listed).

        Called while the native handle exists but the window is unmapped
        (prepare_initial_state), so there is no taskbar flash to race.
        """
        if not self.is_available():
            return
        try:
            hwnd = int(window.winId())
        except Exception:
            return
        identity = bool(getattr(window, "WIN_TASKBAR_IDENTITY", False))
        if identity:
            self._flip_ex(hwnd, add=WS_EX_NOACTIVATE | WS_EX_APPWINDOW,
                          remove=WS_EX_TOOLWINDOW)
        else:
            self._flip_ex(hwnd, add=WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                          remove=WS_EX_APPWINDOW)
        overlay_trace(
            f"win32 set_initial_state: pre-map NOACTIVATE+"
            f"{'APPWINDOW (taskbar identity)' if identity else 'TOOLWINDOW (skip taskbar)'}")

    def set_above(self, window) -> None:
        """Re-assert topmost (showEvent parity with the EWMH ABOVE re-send)."""
        if not self.is_available():
            return
        try:
            hwnd = int(window.winId())
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                | win32con.SWP_NOACTIVATE)
        except Exception:
            pass

    def set_non_activating(self, window) -> None:
        """Re-assert the skip-taskbar/no-activate bits (idempotent, per show)."""
        if not self.is_available():
            return
        try:
            hwnd = int(window.winId())
        except Exception:
            return
        if bool(getattr(window, "WIN_TASKBAR_IDENTITY", False)):
            self._flip_ex(hwnd, add=WS_EX_NOACTIVATE)
        else:
            self._flip_ex(hwnd, add=WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def set_rep_initial_state(self, window) -> None:
        """No-op: the representative is never constructed on Windows
        (wants_taskbar_rep() is False; the cluster owns the entry)."""
        overlay_trace("win32 set_rep_initial_state: no-op (rep unused on Windows)")

    def set_skip_close_animation(self, window) -> None:
        return  # no KWin close animation to skip

    def set_window_opacity(self, window, opacity: float) -> None:
        """Whole-window opacity via Qt (SetLayeredWindowAttributes underneath).

        Probe P3: setWindowOpacity(0) hides a translucent top-level and
        setWindowOpacity(1) restores it pixel-identically, so the content
        blanking / paint-staging machinery keeps its semantics on Windows.
        """
        try:
            window.setWindowOpacity(max(0.0, min(1.0, float(opacity))))
        except Exception:
            pass

    # -- input shape (the actual Windows work) ----------------------------

    def apply_input_shape(self, window, path, dpr: float) -> None:
        """Logical-coord QPainterPath -> device-px region -> arbiter entry.

        Single conversion point shared with the X11 backend
        (region.device_input_region); the caller never touches device pixels.
        """
        if not self.is_available():
            return
        from utils.overlay.region import device_input_region
        self.apply_input_region(window, device_input_region(path, dpr))

    def apply_input_region(self, window, region) -> None:
        if not self.is_available() or region is None:
            return
        try:
            hwnd = int(window.winId())
        except Exception:
            return
        self._arbiter.set_region(hwnd, region)
        self._update_timer()

    def clear_input_region(self, window) -> None:
        if not self.is_available():
            return
        try:
            hwnd = int(window.winId())
        except Exception:
            return
        self._arbiter.clear(hwnd)
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
            overlay_trace("win32 arbiter: 60 Hz cursor poll STARTED")
        elif not need and self._timer is not None:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None
            overlay_trace("win32 arbiter: cursor poll stopped (no dynamic regions)")

    def _on_tick(self) -> None:
        self._arbiter.tick()
        # Entries can self-evict on a dead window; stop polling when drained.
        if not self._arbiter.needs_polling:
            self._update_timer()
