"""Parentless, frameless, always-on-top, non-activating widget surface.

Hosts a single borrowed child widget that fills it completely. The surface
paints nothing; the hosted widget paints its own opaque body.
"""
from __future__ import annotations

import os
import sys
from enum import Enum

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QWidget, QVBoxLayout

from utils.overlay.backend import OverlayBackend, get_overlay_backend, overlay_trace

# Explicit truthy tokens (mirrors overlay_entry's falsey set) for the
# TTMT_OVERLAY_UNMANAGED escape hatch below.
_TRUTHY = {"1", "yes", "y", "true", "t", "on"}


def _use_nonactivating_panel() -> bool:
    """cocoa QPA only: realize overlay surfaces as Qt.Tool -> NSPanel.

    On macOS a click on an interactive region of a plain NSWindow ACTIVATES
    the app (the focused game loses key - probed, CP2 in the macOS overlay
    probe ledger), and only an NSPanel accepts the NonactivatingPanelMask
    that prevents it (CP2-C: 58 clicks, zero activations). The macOS backend
    applies that mask pre-map (set_initial_state) and cures the NSPanel
    hide-on-app-deactivate default the same way.

    This is a deliberate exception to the "plain Qt.Window, never Qt.Tool"
    rule in __init__ below: that rule is X11-motivated (KWin minimized Tool
    windows with the main window and lost SKIP_TASKBAR on the recreated
    handles). Neither applies on cocoa - the main window is HIDDEN (not
    minimized) in float mode, and macOS has no taskbar hints to lose.
    Off-cocoa (xcb, win32, offscreen tests) nothing changes."""
    if sys.platform != "darwin":
        return False
    try:
        from PySide6.QtGui import QGuiApplication
        return (QGuiApplication.instance() is not None
                and QGuiApplication.platformName() == "cocoa")
    except Exception:
        return False


def _bypass_wm_enabled() -> bool:
    """True when TTMT_OVERLAY_UNMANAGED opts back into OVERRIDE-REDIRECT
    (WM-bypassed) overlay windows - the pre-managed behavior. Default OFF:
    surfaces are MANAGED keep-above windows, which stay above the game windows
    but BELOW the compositor's system layers (screenshot region selection,
    OSDs, lock screen). Override-redirect windows sit above those system
    layers too, which is exactly the screenshot-UI conflict this default
    fixes; the escape hatch exists in case a WM mishandles managed placement
    (clamping, repositioning) that override-redirect was immune to."""
    return os.environ.get("TTMT_OVERLAY_UNMANAGED", "").strip().lower() in _TRUTHY


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

    # EWMH window type the backend writes pre-map (x11_backend.set_initial_state).
    # DOCK exempts managed windows from KWin's fit-to-desktop move clamp while
    # stacking over the games, and is not animated by the slidingnotifications
    # effect (which painted the ring traveling in from a stale position -
    # bisected live + source-verified). The radial/panel subclasses override
    # this with the KDE OSD type: a strictly higher layer that KWin's internal
    # click-raise cannot cross, so an emblem press can never lift the cluster's
    # internal dim above them. DISPROVEN alternatives (probed, do not revisit):
    # dock+keep-above does NOT elevate above plain docks; WM_TRANSIENT_FOR is
    # NOT honored against KWin's internal raiseWindow; NOTIFICATION and
    # CRITICAL_NOTIFICATION are both move-animated by slidingnotifications.
    WM_WINDOW_TYPE = "_NET_WM_WINDOW_TYPE_DOCK"

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
        #
        # MANAGED by default (no X11BypassWindowManagerHint): a managed frameless
        # keep-above window sits in the WM's "above" layer - over the game windows
        # (all this overlay must beat) but BELOW the compositor's system layers
        # (screenshot region selection, OSDs, lock screen). The old
        # override-redirect mode stacked above those system layers too, so the
        # cluster covered e.g. the region-screenshot UI. Managed mode leans on
        # machinery that already exists: the controller sets geometry BEFORE
        # show (program-specified position, so the WM honors placement), the
        # backend writes _NET_WM_STATE (ABOVE + SKIP_TASKBAR/PAGER) plus a DOCK
        # _NET_WM_WINDOW_TYPE as pre-map properties, and showEvent re-asserts
        # the state per show - those calls were belt-and-suspenders under
        # override-redirect and are load-bearing now. The DOCK type is what
        # exempts these windows from KWin's fit-to-desktop clamp on client
        # moves (see x11_backend.set_initial_state) - without it the fixed
        # max-scale envelope walls against the desktop bounds well short of the
        # visible content reaching a screen edge. TTMT_OVERLAY_UNMANAGED=1
        # restores override-redirect in case a WM mishandles managed placement.
        # cocoa exception (probe-backed; see _use_nonactivating_panel): the
        # base type becomes Qt.Tool so the native window is an NSPanel and the
        # macOS backend can apply the nonactivating mask pre-map.
        panel = _use_nonactivating_panel()
        flags = (
            (Qt.Tool if panel else Qt.Window)
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        bypass = _bypass_wm_enabled()
        if bypass:
            flags |= Qt.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        # Running-code stamp: live validation must be able to prove which window
        # mode this build is actually running (TTMT_OVERLAY_TRACE=1 to see it).
        overlay_trace(
            f"{type(self).__name__} window mode: "
            + ("UNMANAGED override-redirect (TTMT_OVERLAY_UNMANAGED)" if bypass
               else ("MANAGED nonactivating panel (cocoa)" if panel
                     else "MANAGED keep-above (default)")))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Explicitly keep WA_DeleteOnClose OFF to avoid destroying a borrowed widget.
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        # Overlay surfaces are manually geometried and may legitimately extend
        # past screen edges (the fixed cluster envelope is taller than a laptop
        # screen). cocoa feeds safe-area margins (menu bar / notch / off-screen
        # overlap) into the layout by default, silently pushing the hosted
        # content DOWN inside the window while the input region, anchor model,
        # and every mapToGlobal consumer stay at the window origin - painted
        # reality and click reality diverge by the margin (live: emblem drawn
        # 201px below its clickable disc, all clicks dead). Opt out: content
        # must fill the window rect exactly, everywhere, on every platform.
        self.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)

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
        # Hosting into an ALREADY-VISIBLE surface (the persistent radial/panel
        # windows, kept mapped between opens): reparenting hides the widget and
        # Qt does not implicitly re-show a child added to a visible parent, so
        # show it explicitly. A hidden surface shows its children on map as before.
        if self.isVisible():
            widget.show()
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
    # Close protection
    # ------------------------------------------------------------------

    def closeEvent(self, ev) -> None:
        """Refuse user/WM-originated (spontaneous) closes.

        The controller owns these surfaces' lifecycle and tears them down with
        hide()/deleteLater(), never close(). A stray "close window" keybind
        (e.g. Ctrl+C bound at the desktop level) or a WM close action must NOT be
        able to destroy the emblem or a card surface, which would leave the
        cluster on screen but unrecoverable. Programmatic closes (app shutdown,
        QApplication.closeAllWindows) are spontaneous=False and proceed normally.
        """
        if ev.spontaneous():
            ev.ignore()
            return
        ev.accept()

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

    def apply_input_region(self, region) -> None:
        """Set the X11 ShapeInput region directly from a device-pixel QRegion.

        Used for disjoint regions (the card's controls-only click-through region),
        where a single polygonized path is unreliable. Delegates to the backend's
        region path; a no-op before show() (the backend swallows an invalid winId).
        """
        self._backend.apply_input_region(self, region)

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
        self._scaled_view = None  # ScaledCardView holding the borrowed card
        self._peeking = False  # transparent hover-peek state (dim driven by controller)

    @property
    def surface_id(self) -> int:
        return self._surface_id

    @property
    def shape_mode(self) -> ShapeMode:
        return self._shape_mode

    def set_input_shape_mode(self, mode: ShapeMode) -> None:
        """Switch between PINWHEEL_BITE (attached) and ROUNDED_RECT (detached)."""
        self._shape_mode = mode

    @property
    def is_peeking(self) -> bool:
        return self._peeking

    def set_peek(self, active: bool, control_rects=None) -> None:
        """Record hover-peek state. The dim RENDERING is driven by the controller
        (uniform card opacity here via set_content_opacity, plus an extra body-fill
        dim through the card provider); this surface only tracks the flag so other
        code can query is_peeking."""
        self._peeking = bool(active)

    def set_content_opacity(self, opacity: float) -> None:
        """Composite the whole hosted card at *opacity* (hover-peek). Delegates to
        the ScaledCardView proxy; no-op before a card is hosted."""
        if self._scaled_view is not None:
            self._scaled_view.set_content_opacity(opacity)

    def set_scale(self, scale: float) -> None:
        """Record the current overlay zoom factor (0.5-1.75).

        This is the group/user scale, NOT the device-pixel ratio.  The
        controller drives the actual path recompute; this just persists state.
        """
        self._scale = scale

    def host(self, widget: QWidget, base_size=None) -> None:  # type: ignore[override]
        """Host the borrowed card THROUGH a ScaledCardView so it scales as a unit.

        base_size is the framed 1.0 card size as (w, h); the card is fixed to it
        so the proxy scene rect is stable, and then scaled by the view transform
        (driven later via set_card_scale).  Passing no base_size leaves the card
        at its natural size.
        """
        if widget is None:
            return
        from utils.overlay.scaled_card_view import ScaledCardView
        if self._scaled_view is not None:
            self.release()
        # NOTE: unlike OverlaySurface.host, this override does not run the
        # cross-surface stale-_hosted guard, because cards are only ever hosted
        # into CardSurfaces (tracked via _scaled_view, never _hosted) and the
        # controller always release()s before re-hosting. ScaledCardView.set_card
        # detaches the card from its grid parent before embedding it.
        if base_size is not None:
            widget.setFixedSize(int(base_size[0]), int(base_size[1]))
        view = ScaledCardView()
        view.set_card(widget)
        self._scaled_view = view
        self._layout.addWidget(view)

    def release(self) -> "QWidget | None":  # type: ignore[override]
        """Un-proxy the borrowed card, clear the fixed-size constraints, and
        remove the ScaledCardView from the layout.

        The fixed size imposed by host() (min==max==base_size) is cleared here
        so the framed grid can re-fit the card when it is restored after leave.
        Returns the card (parentless, undeleted) or None if nothing was hosted.
        """
        view = self._scaled_view
        if view is None:
            return None
        card = view.release_card()
        # Clear the fixed size we imposed for proxying: setFixedSize sets
        # min==max==base, and the restore path only restores the size policy, not
        # the min/max constraints, so without this the card stays clamped after
        # leave and the grid cannot re-fit it.
        if card is not None:
            card.setMinimumSize(0, 0)
            card.setMaximumSize(16777215, 16777215)
        self._layout.removeWidget(view)
        self._scaled_view = None
        view.deleteLater()  # the view is owned by the surface; the card was borrowed
        return card

    def set_card_scale(self, scale: float) -> None:
        """Drive the per-card QGraphicsView transform to zoom the hosted card."""
        self._scale = float(scale)
        if self._scaled_view is not None:
            self._scaled_view.set_scale(scale)

    def closeEvent(self, ev):
        # Honour the base's spontaneous-close refusal first. Only release the
        # borrowed card when the close is actually going through (a programmatic
        # close); a refused (spontaneous) close must leave the card hosted.
        super().closeEvent(ev)
        if ev.isAccepted():
            # Belt for the close() path: release the borrowed card before Qt's
            # destruction cascade so the ScaledCardView's scene never deletes it.
            self.release()


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

    def paintEvent(self, ev) -> None:
        """SOURCE-clear the whole window to transparent on every paint.

        The base OverlaySurface paints nothing, so Qt's partial-update flushes only
        the hosted _Emblem disc region; the square window's CORNERS (outside the
        disc) are never written to the native ARGB backing and retain stale/opaque
        content. KWin then composites that as a dark 'square backdrop' for one frame
        when the parked emblem is revealed at the scale-gesture settle (visible
        because, since the judder fix, the emblem is no longer raised+composited
        during the hold). An explicit full-rect transparent source-clear forces the
        corners into the backing every repaint, so the reveal is clean. The hosted
        _Emblem child paints its disc over this transparent fill as usual."""
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.end()
