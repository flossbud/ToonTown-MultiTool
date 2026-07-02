"""X11 input-shape backend: punches click-through holes via the X Shape extension.

Region is pushed as ShapeInput rectangles so the pointer falls through everything
NOT in the region to the window behind. Bounding/clip shape is left untouched
(rendering is unaffected; translucency handles the visuals)."""
from __future__ import annotations

from PySide6.QtGui import QRegion
from utils.overlay.backend import OverlayBackend, overlay_trace


def region_to_rects(region: QRegion) -> list[tuple[int, int, int, int]]:
    return [(r.x(), r.y(), r.width(), r.height()) for r in region]  # PySide6 6.10: QRegion is iterable; no .rects()


class X11OverlayBackend(OverlayBackend):
    def __init__(self):
        self._display = None
        self._shape = None
        from utils.overlay.backend import overlay_trace
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import shape
            self._display = xdisplay.Display()
            if self._display.query_extension("SHAPE") is None:
                self._display = None
                overlay_trace("X11OverlayBackend: SHAPE extension NOT advertised by server")
            else:
                self._shape = shape
                overlay_trace("X11OverlayBackend: Display OK, SHAPE available")
                # Swallow asynchronous protocol errors on THIS connection. The
                # EWMH/SHAPE requests are best-effort and fire-and-flush, so their
                # errors (e.g. BadWindow if a surface's native handle was torn down
                # between the winId() read and the server processing the request)
                # arrive asynchronously and bypass the per-call try/except - Xlib's
                # default handler would otherwise spam them to stderr. This handler
                # is connection-local; Qt uses a separate display, so this never
                # masks errors outside the overlay backend.
                self._display.set_error_handler(self._on_x_error)
        except Exception as e:
            self._display = None
            import traceback
            overlay_trace(f"X11OverlayBackend init FAILED: {e!r}\n" + traceback.format_exc())

    @staticmethod
    def _on_x_error(*_args) -> None:
        """Ignore async X protocol errors on the backend's own connection."""
        return None

    def is_available(self) -> bool:
        return self._display is not None and self._shape is not None

    def set_overlay_hints(self, window) -> None:
        # Window flags (frameless/on-top) are set on the Qt side; nothing extra here yet.
        return

    def set_initial_state(self, window) -> None:
        """Set _NET_WM_STATE and _NET_WM_WINDOW_TYPE as PROPERTIES before map.

        This is the EWMH-canonical way to request a window's INITIAL state: the WM
        reads it when it manages (maps) the window, so above + skip-taskbar/pager
        take effect from the first frame with no post-map race. The post-map
        ClientMessages (set_above/set_non_activating) re-assert it afterwards in
        case the WM re-evaluates the window (e.g. when the main window minimizes).
        Must be called while the window is realized (winId valid) but NOT yet
        mapped (before show()).

        The window TYPE (the surface class's ``WM_WINDOW_TYPE``, DOCK for every
        overlay surface) is load-bearing for MANAGED overlay windows: KWin
        force-fits a managed NORMAL window's client-requested geometry into the
        virtual-desktop bounding box, which walled the cluster's fixed
        max-scale envelope short of the top screen edge and desynced the drag
        anchor from the pinned window. DOCK windows are exempt from that clamp
        - probed empirically on KWin 6.7.1, 2026-07-01, with keep-above
        applied, i.e. exactly this configuration - and, unlike NOTIFICATION,
        are not animated by the slidingnotifications effect (which painted the
        radial ring traveling in from a stale position; live-bisected). With
        _NET_WM_STATE_ABOVE also set the dock stacks in the same keep-above
        layer as before (over the games, still below the compositor's system
        layers such as the screenshot region picker), and docks are visible on
        all virtual desktops - matching the old override-redirect behavior. No
        _NET_WM_STRUT is set, so no screen space is reserved. The radial/panel
        stacking above the cluster is enforced by ``set_transient_for``. On an
        override-redirect window (TTMT_OVERLAY_UNMANAGED=1) the WM ignores
        these properties, so writing them unconditionally is harmless.
        """
        if not self.is_available():
            return
        try:
            from Xlib import X, Xatom
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            a = d.intern_atom
            win.change_property(
                a("_NET_WM_STATE"),
                Xatom.ATOM,
                32,
                [
                    a("_NET_WM_STATE_ABOVE"),
                    a("_NET_WM_STATE_SKIP_TASKBAR"),
                    a("_NET_WM_STATE_SKIP_PAGER"),
                ],
                X.PropModeReplace,
            )
            wtype = getattr(window, "WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK")
            win.change_property(
                a("_NET_WM_WINDOW_TYPE"),
                Xatom.ATOM,
                32,
                [a(wtype)],
                X.PropModeReplace,
            )
            d.flush()
            overlay_trace("x11 set_initial_state: pre-map _NET_WM_STATE"
                          f"(above+skip) + _NET_WM_WINDOW_TYPE({wtype}) applied")
        except Exception:
            pass

    def set_transient_for(self, window, parent) -> None:
        """Set WM_TRANSIENT_FOR = *parent*'s window, PRE-MAP (both realized).

        Load-bearing for the overlay stacking: KWin keeps a transient ABOVE its
        parent in EVERY restack computation - probed on KWin 6.7.1 (2026-07-01):
        neither ``parent.raise_()`` nor an explicit ``child.lower()`` can invert
        the order, so KWin's internal click-raise of the (click-accepting)
        cluster window can never lift it - and its internal dim - above the
        radial/panel. This replaces the earlier NOTIFICATION-type layering,
        which collided with the ``slidingnotifications`` effect: it paints
        notification windows with a translation toward their geometry, so a
        window whose moves accumulated invisibly (zero damage while empty)
        visibly replayed the whole travel on its first content paint. DOCK
        windows are not animated by it (bisected live) and keep the
        fit-to-desktop clamp exemption, transient or not (probed)."""
        if not self.is_available():
            return
        try:
            from Xlib import Xatom
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            win.change_property(
                d.intern_atom("WM_TRANSIENT_FOR"),
                Xatom.WINDOW,
                32,
                [int(parent.winId())],
            )
            d.flush()
            overlay_trace("x11 set_transient_for: WM_TRANSIENT_FOR applied "
                          f"({int(window.winId()):#x} -> {int(parent.winId()):#x})")
        except Exception:
            pass

    def set_above(self, window) -> None:
        """EWMH: request the WM to keep this window above all others."""
        if not self.is_available():
            return
        try:
            from Xlib import X
            from Xlib.protocol import event as xevent
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            a = d.intern_atom
            ev = xevent.ClientMessage(
                window=win,
                client_type=a("_NET_WM_STATE"),
                data=(32, [1, a("_NET_WM_STATE_ABOVE"), 0, 1, 0]),
            )
            d.screen().root.send_event(
                ev,
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
            )
            d.flush()
        except Exception:
            pass

    def set_non_activating(self, window) -> None:
        """EWMH: hide this window from the taskbar and pager.

        Qt.Tool alone is insufficient for a parentless overlay on KWin; send
        _NET_WM_STATE_SKIP_TASKBAR + _NET_WM_STATE_SKIP_PAGER explicitly.
        Pattern proven in the multi-window spike.
        """
        if not self.is_available():
            return
        try:
            from Xlib import X
            from Xlib.protocol import event as xevent
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            a = d.intern_atom
            ev = xevent.ClientMessage(
                window=win,
                client_type=a("_NET_WM_STATE"),
                data=(32, [1, a("_NET_WM_STATE_SKIP_TASKBAR"), a("_NET_WM_STATE_SKIP_PAGER"), 1, 0]),
            )
            d.screen().root.send_event(
                ev,
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
            )
            d.flush()
        except Exception:
            pass

    def set_skip_close_animation(self, window) -> None:
        """Ask KWin to skip its close/hide animation for this window.

        Set _KDE_NET_WM_SKIP_CLOSE_ANIMATION = 1 so dropping the scale proxy is
        an instant unmap with no fade-out. Best-effort: a property-set failure
        must never block the drop. Requires a realized winId.
        """
        if not self.is_available():
            return
        try:
            from Xlib import X, Xatom
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            win.change_property(
                d.intern_atom("_KDE_NET_WM_SKIP_CLOSE_ANIMATION"),
                Xatom.CARDINAL,
                32,
                [1],
                X.PropModeReplace,
            )
            d.flush()
        except Exception:
            pass

    def apply_input_shape(self, window, path, dpr: float) -> None:
        """Apply a logical-coord QPainterPath as the X11 ShapeInput region.

        *path* is in logical surface-local coords; *dpr* converts to device
        pixels.  device_input_region() is the single conversion point - the
        caller never touches device pixels directly.
        """
        if not self.is_available():
            return
        from utils.overlay.region import device_input_region
        region = device_input_region(path, dpr)
        self.apply_input_region(window, region)

    def apply_input_region(self, window, region) -> None:
        if not self.is_available() or region is None:
            return
        from Xlib import X
        rects = region_to_rects(region)
        try:
            xwin = self._display.create_resource_object("window", int(window.winId()))
            xwin.shape_rectangles(self._shape.SO.Set, self._shape.SK.Input, X.Unsorted, 0, 0, rects)
            self._display.flush()
        except Exception:
            pass  # never crash the UI on a shape failure; caller surfaces readiness

    def clear_input_region(self, window) -> None:
        if not self.is_available():
            return
        try:
            xwin = self._display.create_resource_object("window", int(window.winId()))
            xwin.shape_mask(self._shape.SO.Set, self._shape.SK.Input, 0, 0, None)
            self._display.flush()
        except Exception:
            pass
