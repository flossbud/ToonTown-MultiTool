"""X11 input-shape backend: punches click-through holes via the X Shape extension.

Region is pushed as ShapeInput rectangles so the pointer falls through everything
NOT in the region to the window behind. Bounding/clip shape is left untouched
(rendering is unaffected; translucency handles the visuals)."""
from __future__ import annotations

from PySide6.QtGui import QRegion
from utils.overlay.backend import OverlayBackend


def region_to_rects(region: QRegion) -> list[tuple[int, int, int, int]]:
    return [(r.x(), r.y(), r.width(), r.height()) for r in region]  # PySide6 6.10: QRegion is iterable; no .rects()


class X11OverlayBackend(OverlayBackend):
    def __init__(self):
        self._display = None
        self._shape = None
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import shape
            self._display = xdisplay.Display()
            if self._display.query_extension("SHAPE") is None:
                self._display = None
            else:
                self._shape = shape
        except Exception:
            self._display = None

    def is_available(self) -> bool:
        return self._display is not None and self._shape is not None

    def set_overlay_hints(self, window) -> None:
        # Window flags (frameless/on-top/Tool) are set on the Qt side; nothing extra here yet.
        return

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
