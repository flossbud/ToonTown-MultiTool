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
