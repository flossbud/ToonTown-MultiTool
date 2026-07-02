"""Taskbar 'representative' for Float UI (single-window cluster path).

While Float UI is active the main window is HIDDEN (no taskbar entry, no
Alt-Tab entry, nothing that can restore the gutted window UI). This small
NORMAL-type top-level takes the app's place in the taskbar and Alt-Tab:

- LISTED: no skip-taskbar/skip-pager hints and the default NORMAL window type
  (KWin's TabBox filters DOCK windows - probe A 2026-07-02; a plain NORMAL
  frameless window gets taskbar entry + live preview + Alt-Tab + preview-X
  close - probe B control run). It MUST accept focus: KWin's TabBox only
  lists focus-accepting windows. An activation via taskbar click or Alt-Tab
  therefore takes focus like any window switch - user-initiated, reversible,
  and harmless (the float UI is keep-above, so it is already frontmost).
- HIDDEN IN PLAIN SIGHT (aligned-mirror invariant): the rep is MAPPED (live
  thumbnail) and positioned pixel-aligned UNDER the cluster's content bbox,
  in the below-normal layer (keep-below; games=normal and cluster=dock always
  stack over it). It paints ONLY fully-opaque mirror pixels (the controller
  strips sub-opaque ones), so every pixel it shows is covered by an identical
  cluster pixel above it - invisible by construction. Opacity-0 CANNOT be the
  mechanism: KWin applies window opacity to thumbnails too (probe B,
  2026-07-02) - it is instead the BLANKING tool (``set_blanked``) for gesture
  windows (drag/zoom/peek/radial-dim) where alignment cannot be guaranteed.
- CLOSE = QUIT: a spontaneous close (taskbar Close action / preview X) is
  refused - the controller owns this window's lifecycle - and routed to the
  owner's quit callback (the main window's close() -> shutdown path, the same
  route the radial Exit spoke takes). Programmatic closes (app shutdown /
  closeAllWindows) proceed normally.
- MINIMIZE IS BOUNCED: a minimized rep would freeze into a stale snapshot
  (probe C proved minimize caches the composited image); a WM-initiated
  minimize is restored immediately.

The controller feeds the mirror via ``set_mirror``: immediately on every
composition change (the preview is composition-accurate), plus a RARE
safety-net tick (``on_tick``) so long-lived in-card text (timers) does not
freeze entirely - preview text may lag up to the tick interval, an accepted
trade in this judder-sensitive codebase. Mapped-window repaints are invisible
on screen (covered) and free of any compositor animation.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import get_overlay_backend, overlay_trace

# RARE safety-net mirror refresh. Composition changes re-grab immediately via
# the controller; this tick only keeps long-lived in-card text (timers) from
# freezing entirely, so preview text may lag up to 10s - accepted. Kept rare
# on purpose: every grab walks the whole cluster paint path (judder-sensitive
# codebase, the taskbar preview is decorative).
MIRROR_TICK_MS = 10_000


class TaskbarRepresentative(QWidget):
    """The float-UI taskbar/Alt-Tab stand-in. See the module docstring."""

    def __init__(self, on_close_requested=None, on_tick=None, backend=None,
                 title: str | None = None) -> None:
        # Parentless top-level: must not be coupled to any other window's state.
        super().__init__(None)
        self._backend = backend if backend is not None else get_overlay_backend()
        self._on_close_requested = on_close_requested
        self._on_tick = on_tick
        self._mirror: QPixmap | None = None
        self._blanked = False
        # Plain frameless top-level that ACCEPTS focus (no WindowDoesNotAcceptFocus:
        # KWin's TabBox skips focus-refusing windows and Alt-Tab listing is a
        # requirement). WA_ShowWithoutActivating keeps the initial map from
        # stealing the game's focus at float enter. Translucent: the mirror's
        # transparent pixels must stay transparent on screen or the rep would
        # paint an opaque rectangle out from under the cluster.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        if title is None:
            try:
                from utils.build_flavor import window_title
                title = window_title()
            except Exception:
                title = "ToonTown MultiTool"
        self.setWindowTitle(title)
        self._tick = QTimer(self)
        self._tick.setInterval(MIRROR_TICK_MS)
        self._tick.timeout.connect(self._fire_tick)

    # ------------------------------------------------------------------
    # WM identity
    # ------------------------------------------------------------------
    def prepare_initial_state(self) -> None:
        """Pre-map hints: keep-below + empty input shape. Mirrors the cluster
        surface's prepare-before-show discipline so this window never maps
        above anything or blocks a click on its first frame. Deliberately NO
        opacity write: the rep maps ALIGNED under the cluster with the mirror
        already painted (invisible by construction); opacity is reserved for
        ``set_blanked``."""
        from PySide6.QtGui import QRegion
        self._backend.set_rep_initial_state(self)
        self._backend.apply_input_region(self, QRegion())
        overlay_trace("taskbar_rep: prepared (below + click-through, aligned mirror)")

    def set_blanked(self, blanked: bool) -> None:
        """Blank (opacity 0) while the cluster is mid-gesture/peek/dim - any
        state where the aligned-mirror invariant cannot hold. Blanking also
        blanks the taskbar/Alt-Tab preview (KWin composites opacity into
        thumbnails - probed), an accepted transient. Idempotent."""
        blanked = bool(blanked)
        if blanked == self._blanked:
            return
        self._blanked = blanked
        self._backend.set_window_opacity(self, 0.0 if blanked else 1.0)

    def is_blanked(self) -> bool:
        return self._blanked

    # ------------------------------------------------------------------
    # Mirror content (what the taskbar thumbnail renders)
    # ------------------------------------------------------------------
    def set_mirror(self, pixmap: QPixmap | None) -> None:
        """Install a new cropped mirror of the float UI. Resizes to the mirror's
        device-independent size so the thumbnail aspect equals the content bbox."""
        self._mirror = pixmap
        if pixmap is not None and not pixmap.isNull():
            size = pixmap.deviceIndependentSize().toSize()
            if size.isValid() and not size.isEmpty() and size != self.size():
                self.resize(size)
        self.update()

    def paintEvent(self, ev) -> None:
        if self._mirror is None or self._mirror.isNull():
            return
        p = QPainter(self)
        p.drawPixmap(self.rect(), self._mirror)
        p.end()

    # ------------------------------------------------------------------
    # Slow refresh tick (runs only while shown)
    # ------------------------------------------------------------------
    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._tick.start()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._tick.stop()

    def _fire_tick(self) -> None:
        cb = self._on_tick
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass  # a mirror-refresh failure must never break the timer chain

    # ------------------------------------------------------------------
    # Close = quit; minimize = bounce
    # ------------------------------------------------------------------
    def closeEvent(self, ev) -> None:
        """Spontaneous close (taskbar Close, preview X) = QUIT THE APP, routed
        to the owner's callback DEFERRED (never re-enter the WM close handshake
        synchronously). The close itself is refused - the controller owns this
        window's lifecycle (hide()/deleteLater(), never close()). Programmatic
        closes (app shutdown, closeAllWindows) proceed."""
        if ev.spontaneous():
            ev.ignore()
            cb = self._on_close_requested
            if cb is not None:
                QTimer.singleShot(0, cb)
            return
        ev.accept()

    def changeEvent(self, ev) -> None:
        super().changeEvent(ev)
        if ev.type() == QEvent.WindowStateChange and self.isMinimized():
            # A minimized rep freezes the taskbar preview into a stale snapshot:
            # bounce back. Deferred so the WM's state change settles before the
            # counter-request; context-object form so the pending bounce dies
            # with the widget instead of firing on a destroyed one.
            QTimer.singleShot(0, self, self.showNormal)
