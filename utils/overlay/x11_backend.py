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

        The window TYPE (the surface class's ``WM_WINDOW_TYPE``: DOCK for the
        cluster, OSD for the radial/panel) is load-bearing for MANAGED overlay
        windows: KWin force-fits a managed NORMAL window's client-requested
        geometry into the virtual-desktop bounding box, which walled the
        cluster's fixed max-scale envelope short of the top screen edge and
        desynced the drag anchor from the pinned window. DOCK and OSD windows
        are exempt from that clamp - probed empirically on KWin 6.7.1 with
        keep-above applied, i.e. exactly this configuration - and neither is
        animated by the slidingnotifications effect (which matched the earlier
        NOTIFICATION/CRITICAL_NOTIFICATION typings and painted the radial ring
        traveling in from a stale position; live-bisected + source-verified).
        The dock stacks over the games but below the compositor's system
        layers (screenshot region picker), and docks are visible on all
        virtual desktops - matching the old override-redirect behavior. No
        _NET_WM_STRUT is set, so no screen space is reserved. The radial/panel
        OSD layer sits strictly above the dock layer, which KWin's internal
        click-raise cannot cross - see ``RadialSurface.WM_WINDOW_TYPE``. On an
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
            # _NET_WM_WINDOW_TYPE is an ordered PREFERENCE LIST: the WM takes
            # the first atom it recognizes. KWin knows the KDE OSD atom and
            # keeps its probed layer behavior; mutter does not (it skips
            # unknown atoms - window-props.c reload_net_wm_window_type), so
            # without a recognized fallback it types the surface NORMAL (or
            # DIALOG once WM_TRANSIENT_FOR is set) and constrain_titlebar_
            # visible clamps its top edge to the workarea - which shoved the
            # ring canvas 115px off the emblem when the anchor sat near the
            # top screen edge (GNOME 50 live, 2026-07-12). Surfaces declare
            # mutter-recognized fallbacks via WM_WINDOW_TYPE_FALLBACKS.
            wtype_fallbacks = getattr(window, "WM_WINDOW_TYPE_FALLBACKS", ())
            win.change_property(
                a("_NET_WM_WINDOW_TYPE"),
                Xatom.ATOM,
                32,
                [a(wtype)] + [a(f) for f in wtype_fallbacks],
                X.PropModeReplace,
            )
            d.flush()
            overlay_trace("x11 set_initial_state: pre-map _NET_WM_STATE"
                          f"(above+skip) + _NET_WM_WINDOW_TYPE({wtype}"
                          f"{''.join(',' + f for f in wtype_fallbacks)}) applied")
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

    def set_rep_initial_state(self, window) -> None:
        """Pre-map state for the taskbar REPRESENTATIVE: keep-below only.

        Deliberately NO skip-taskbar / skip-pager (being listed is the whole
        point) and NO _NET_WM_WINDOW_TYPE write (the default NORMAL type is
        what Plasma's task manager and KWin's TabBox list - probe B control run,
        2026-07-02; DOCK is taskbar-listed but Alt-Tab-filtered - probe A).
        BELOW keeps the rep in the below-normal layer: games (normal) and the
        cluster (dock) always stack over it, so anything covering the mirror
        area hides it MORE - the aligned-mirror invariant only has to hold over
        bare desktop.
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
                [a("_NET_WM_STATE_BELOW")],
                X.PropModeReplace,
            )
            d.flush()
            overlay_trace("x11 set_rep_initial_state: pre-map BELOW "
                          "(listed in taskbar/Alt-Tab by design)")
        except Exception:
            pass

    def set_window_opacity(self, window, opacity: float) -> None:
        """_NET_WM_WINDOW_OPACITY: compositor-applied whole-window opacity as a
        32-bit cardinal fraction of 0xFFFFFFFF. NOTE (probed 2026-07-02): KWin
        applies this to taskbar/Alt-Tab thumbnails too, so 0 blanks the preview
        as well - which is exactly how the representative uses it: a BLANKING
        mechanism for gesture windows where the aligned-mirror invariant cannot
        hold. Best-effort: never raises."""
        if not self.is_available():
            return
        try:
            from Xlib import X, Xatom
            d = self._display
            win = d.create_resource_object("window", int(window.winId()))
            val = max(0, min(0xFFFFFFFF, int(round(float(opacity) * 0xFFFFFFFF))))
            win.change_property(
                d.intern_atom("_NET_WM_WINDOW_OPACITY"),
                Xatom.CARDINAL,
                32,
                [val],
                X.PropModeReplace,
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

    def pin_above(self, window, parent) -> None:
        """Pin *window* above *parent* in the WM's stack: WM_TRANSIENT_FOR ->
        parent, then an explicit _NET_RESTACK_WINDOW (source=pager, Above).

        KWin never needs this (the radial/panel OSD layer sits strictly above
        the dock cluster's layer), but mutter does not recognize the KDE OSD
        type atom: it types those surfaces NORMAL, and keep-above lands them
        AND the dock cluster in the same META_LAYER_TOP - so GNOME's
        raise-on-click on the cluster (the emblem press that OPENS the ring)
        stacked the cluster, and its internal radial dim, over the ring's
        buttons (live-probed via _NET_CLIENT_LIST_STACKING on GNOME 50 /
        mutter, 2026-07-12). WM_TRANSIENT_FOR is the WM-agnostic structural
        constraint: the WM re-applies transient-above-parent on EVERY restack,
        so raising the parent carries this window along (the mechanism
        utils/x11_transient.confine ghost-probed 2026-07-02). The constraint
        is only a lower bound enforced when the WM restacks, so the explicit
        _NET_RESTACK_WINDOW fixes the CURRENT order too. Qt rewrites
        WM_TRANSIENT_FOR on every show(), so callers must (re)assert AFTER
        map. Best-effort: a failure leaves the KWin-correct behavior as is.
        """
        if not self.is_available():
            return
        try:
            from Xlib import X, Xatom
            from Xlib.protocol import event as xevent
            d = self._display
            child_id = int(window.winId())
            parent_id = int(parent.winId())
            win = d.create_resource_object("window", child_id)
            win.change_property(
                d.intern_atom("WM_TRANSIENT_FOR"),
                Xatom.WINDOW,
                32,
                [parent_id],
                X.PropModeReplace,
            )
            # data.l = [source(2=pager/user), sibling, detail, 0, 0]
            ev = xevent.ClientMessage(
                window=win,
                client_type=d.intern_atom("_NET_RESTACK_WINDOW"),
                data=(32, [2, parent_id, X.Above, 0, 0]),
            )
            d.screen().root.send_event(
                ev,
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
            )
            d.flush()
            overlay_trace(f"x11 pin_above: WM_TRANSIENT_FOR {child_id:#x} -> "
                          f"{parent_id:#x} + restack above (radial-pin build)")
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
