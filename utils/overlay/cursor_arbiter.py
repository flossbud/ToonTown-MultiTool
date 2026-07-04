"""Cursor-region arbiter: flips per-window click-through at region boundaries.

Platform-neutral core shared by the Win32 and macOS overlay backends. Neither
OS exposes an input-shape API (the X Shape mechanism the X11 backend uses), so
both implement "interactive only inside this region" the same way: a ~60 Hz
cursor poll that flips a whole-window click-through bit as the pointer crosses
region boundaries. The flip primitive differs per platform and is injected:

- Win32:  WS_EX_TRANSPARENT|WS_EX_LAYERED ex-style flip (probe P2a/P2b,
  docs/superpowers/specs/2026-07-03-win32-overlay-probe-ledger.md)
- macOS:  NSWindow.setIgnoresMouseEvents_ (probe CP2, 0.18 ms mean flip,
  docs/superpowers/specs/2026-07-03-macos-overlay-probe-ledger.md)

Pure logic: all OS access is injected (``cursor_pos()``, ``window_origin(key)``,
``apply_transparent(key, bool)``) so the core is testable off-platform. Keys
are opaque (hwnd on Windows, the surface widget on macOS). Regions are
``QRegion``s in window-local coordinates; the ONE contract that matters is that
``cursor_pos``, ``window_origin``, and the regions share a single coordinate
space (physical px on Windows, logical points on macOS - the arbiter itself
only subtracts and hit-tests). ``window_origin`` returning ``None`` evicts a
dead window.

``applied`` state is cached per key so the flip port only fires on actual
boundary crossings, never per tick. When a native window is RECREATED outside
the arbiter's sight (cocoa PlatformSurface events), the fresh window's default
bit can diverge from the cache - ``invalidate(key)`` drops the cached state and
immediately re-applies the correct one (the ownership rule: this class is the
ONLY writer of the click-through bit on arbitrated surfaces).
"""
from __future__ import annotations

ARBITER_INTERVAL_MS = 16  # ~60 Hz; win32 P2b raced 10/10 at this rate


class CursorRegionArbiter:
    """Flips per-window click-through as the cursor crosses region boundaries.

    Region semantics mirror X Shape exactly:

    - never shaped        -> fully interactive (no arbiter entry)
    - empty region        -> fully click-through (static, never polled)
    - non-empty region    -> arbitrated per cursor position at ~60 Hz
    - clear(key)          -> back to fully interactive
    """

    def __init__(self, cursor_pos, window_origin, apply_transparent):
        self._cursor_pos = cursor_pos
        self._window_origin = window_origin
        self._apply_transparent = apply_transparent
        self._regions: dict = {}   # key -> QRegion (non-empty = dynamic)
        self._applied: dict = {}   # key -> last applied transparent bool

    # -- registration ---------------------------------------------------

    def set_region(self, key, region) -> None:
        """Register/replace *key*'s interactive region and arbitrate it NOW
        (no polling-interval window of stale interactivity)."""
        self._regions[key] = region
        if region.isEmpty():
            # Static: never interactive, no polling needed for this entry.
            self._apply(key, True)
            return
        self._arbitrate(key)

    def clear(self, key) -> None:
        """Forget *key* and restore full interactivity (X: no shape = all input)."""
        self._regions.pop(key, None)
        if key in self._applied:
            self._apply(key, False)
        self._applied.pop(key, None)

    def drop(self, key) -> None:
        """Forget *key* without touching the (dead) window."""
        self._regions.pop(key, None)
        self._applied.pop(key, None)

    def invalidate(self, key) -> None:
        """Drop *key*'s cached applied-state and re-apply the correct one now.

        For native-window recreation (cocoa PlatformSurface): the fresh window
        starts with the OS default click-through bit while the cache still
        holds the old window's state, so the cache-first ``_apply`` would skip
        the correcting call forever on the "same-state" side. No-op for
        unregistered keys.
        """
        self._applied.pop(key, None)
        region = self._regions.get(key)
        if region is None:
            return
        if region.isEmpty():
            self._apply(key, True)
        else:
            self._arbitrate(key)

    @property
    def needs_polling(self) -> bool:
        """True while any registered region is non-empty (dynamic)."""
        return any(not r.isEmpty() for r in self._regions.values())

    # -- arbitration ----------------------------------------------------

    def tick(self) -> None:
        """Arbitrate every dynamic entry against the current cursor."""
        pos = self._cursor_pos()
        if pos is None:
            return
        for key in [k for k, r in self._regions.items() if not r.isEmpty()]:
            self._arbitrate(key, pos)

    def _arbitrate(self, key, pos=None) -> None:
        if pos is None:
            pos = self._cursor_pos()
            if pos is None:
                return
        origin = self._window_origin(key)
        if origin is None:
            self.drop(key)  # window is gone
            return
        from PySide6.QtCore import QPoint
        local = QPoint(int(pos[0]) - int(origin[0]), int(pos[1]) - int(origin[1]))
        inside = self._regions[key].contains(local)
        self._apply(key, not inside)

    def _apply(self, key, transparent: bool) -> None:
        if self._applied.get(key) == transparent:
            return
        # Cache-first: a raising port must not re-fire every tick.
        self._applied[key] = transparent
        try:
            self._apply_transparent(key, transparent)
        except Exception:
            pass
