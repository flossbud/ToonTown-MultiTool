"""Parentless, frameless, always-on-top, non-activating widget surface.

Hosts a single borrowed child widget that fills it completely. The surface
paints nothing; the hosted widget paints its own opaque body.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QWidget, QVBoxLayout

from utils.overlay.backend import OverlayBackend, get_overlay_backend


class ShapeMode(Enum):
    """Input-shape variants for card windows.

    PINWHEEL_BITE: card body with the concave pinwheel bite cut out (used by
        v1 cards while attached to the cluster).
    ROUNDED_RECT:  plain rounded-rect card body, no bite (v2 detached cards).
    """
    PINWHEEL_BITE = "pinwheel_bite"
    ROUNDED_RECT = "rounded_rect"


class OverlaySurface(QWidget):
    """Generic overlay surface for a single borrowed child widget.

    Must be constructed with NO Qt parent so it stays visible when the main
    window is minimized. Window flags and attributes keep it frameless,
    always-on-top, and non-activating.

    OWNERSHIP CONTRACT (load-bearing for the reparent transaction, Task 4.1):
    this surface never OWNS the hosted widget, but Qt's parent-child
    destruction WILL delete the hosted widget if the surface is destroyed
    while still hosting it. Callers MUST call ``release()`` before destroying
    or deallocating the surface. ``WA_DeleteOnClose=False`` only guards the
    ``close()`` path, not destruction/GC.
    """

    def __init__(self, backend: OverlayBackend | None = None) -> None:
        # Parentless: do not pass a parent so this is always a top-level window.
        super().__init__(None)

        self._backend: OverlayBackend = backend if backend is not None else get_overlay_backend()
        self._hosted: QWidget | None = None

        # Independent top-level (Qt.Window), NOT Qt.Tool. A Qt.Tool window is
        # coupled to the application's main window: when the main window is
        # minimized in transparent mode, Qt/KWin minimizes (and destroys the
        # native handle of) every Tool window along with it - which made the whole
        # cluster vanish until each surface was clicked in the taskbar, and lost
        # the SKIP_TASKBAR hint on the recreated handles (the stray taskbar icons).
        # The spec's "independence rule" requires these to survive the main
        # window's minimize, so they are plain frameless top-levels and rely on
        # the explicit _NET_WM_STATE_SKIP_TASKBAR/_SKIP_PAGER hints (set per show)
        # to stay out of the taskbar/pager.
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Explicitly keep WA_DeleteOnClose OFF to avoid destroying a borrowed widget.
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._layout = layout

    # ------------------------------------------------------------------
    # Child management
    # ------------------------------------------------------------------

    def host(self, widget: QWidget) -> None:
        """Reparent *widget* into this surface as the sole full-bleed child.

        If a widget is already hosted, it is released first (no stacking).
        Hosting ``None`` is a no-op (use ``release()`` to clear the surface).
        """
        if widget is None:
            return
        if self._hosted is widget:
            return
        if self._hosted is not None:
            self.release()
        # If the widget is currently hosted by ANOTHER OverlaySurface, release it
        # there first so that surface's _hosted tracking does not go stale (a later
        # release() on it would otherwise orphan the widget out from under us).
        prev = widget.parent()
        if isinstance(prev, OverlaySurface) and prev is not self and prev._hosted is widget:
            prev.release()
        widget.setParent(self)
        self._layout.addWidget(widget)
        self._hosted = widget

    def release(self) -> QWidget | None:
        """Remove the hosted widget from this surface without deleting it.

        Returns the widget (with parent set to None) or None if nothing hosted.
        """
        w = self._hosted
        if w is None:
            return None
        self._layout.removeWidget(w)
        w.setParent(None)  # type: ignore[arg-type]
        self._hosted = None
        return w

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def set_overlay_geometry(self, rect: QRect) -> None:
        """Set size and position in ONE atomic call to avoid single-frame judder.

        Activate this surface's layout first so the hosted widget's CURRENT
        minimum size (which the layout pushes onto this window's minimumSize
        constraint) is up to date before setGeometry. Without this, after the
        hosted card shrinks (apply_metrics on a scale-down), the window's
        minimumSize can still hold the previous, larger value until a later
        layout pass - and setGeometry would clamp the new, smaller width up to
        the stale minimum (seen on the offscreen QPA, which does not propagate
        size hints synchronously). The controller sizes the surface to the card's
        sizeHint (>= its minimumSizeHint), so a current constraint never fights
        the requested rect; a stale one does.
        """
        if self._layout is not None:
            self._layout.activate()
        self.setGeometry(rect)

    # ------------------------------------------------------------------
    # Input-shape delegation
    # ------------------------------------------------------------------

    def apply_shape(self, path: QPainterPath, dpr: float) -> None:
        """Set the X11 ShapeInput region for this surface window.

        Passes *path* (logical coordinates) and *dpr* straight through to the
        backend.  The single logical->device-pixel conversion lives in
        ``backend.apply_input_shape``; this method must NOT scale *path*.

        The surface must be shown (native handle exists) for this to take
        effect; calling before ``show()`` is a silent no-op (the X11 backend
        swallows an invalid winId). The controller applies the shape after show.
        """
        self._backend.apply_input_shape(self, path, dpr)

    def clear_shape(self) -> None:
        """Remove any previously applied ShapeInput region."""
        self._backend.clear_input_region(self)

    # ------------------------------------------------------------------
    # Window hints: initial state (pre-map) + re-assert (post-map)
    # ------------------------------------------------------------------

    def prepare_initial_state(self) -> None:
        """Realize the native window (unmapped) and set its EWMH initial state.

        Call BEFORE show(): this sets _NET_WM_STATE (above + skip-taskbar/pager)
        as a property the WM reads when it maps the window, so the surface never
        flashes in the taskbar. showEvent() re-asserts the same state after map.
        """
        self.winId()  # force native-handle creation without mapping
        try:
            self._backend.set_initial_state(self)
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Re-apply on EVERY show, not once: if the native window handle is ever
        # recreated (e.g. a hide/show cycle), a one-shot latch would leave the new
        # X window without SKIP_TASKBAR/ABOVE - so it would reappear in the taskbar
        # and drop below the games. The EWMH _NET_WM_STATE ADD messages are
        # idempotent, so re-sending them every show is safe.
        # Independent operations: a failure of one must not skip the other, or the
        # surface could end up "above" but still showing in the taskbar.
        try:
            self._backend.set_above(self)
        except Exception:
            pass
        try:
            self._backend.set_non_activating(self)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Specialised surfaces
# ---------------------------------------------------------------------------

class CardSurface(OverlaySurface):
    """Overlay surface for a single toon-card window (slot 0-3).

    The controller (Tasks 3.2/4.x) computes the shaped card-body path from
    CardMetrics and passes it to ``apply_shape``; this class only stores state.
    """

    def __init__(self, surface_id: int, backend: OverlayBackend | None = None) -> None:
        super().__init__(backend=backend)
        self._surface_id: int = surface_id
        self._shape_mode: ShapeMode = ShapeMode.PINWHEEL_BITE
        self._scale: float = 1.0

    @property
    def surface_id(self) -> int:
        return self._surface_id

    @property
    def shape_mode(self) -> ShapeMode:
        return self._shape_mode

    def set_input_shape_mode(self, mode: ShapeMode) -> None:
        """Switch between PINWHEEL_BITE (attached) and ROUNDED_RECT (detached)."""
        self._shape_mode = mode

    def set_scale(self, scale: float) -> None:
        """Record the current overlay zoom factor (0.5-1.75).

        This is the group/user scale, NOT the device-pixel ratio.  The
        controller drives the actual path recompute; this just persists state.
        """
        self._scale = scale


class EmblemSurface(OverlaySurface):
    """Overlay surface for the emblem (pinwheel disc).

    Always disc-shaped; no PINWHEEL_BITE/ROUNDED_RECT mode needed.
    The controller passes the disc path to ``apply_shape``.
    """

    def __init__(self, backend: OverlayBackend | None = None) -> None:
        super().__init__(backend=backend)
        self._scale: float = 1.0

    def set_scale(self, scale: float) -> None:
        """Record the current overlay zoom factor (0.5-1.75)."""
        self._scale = scale
