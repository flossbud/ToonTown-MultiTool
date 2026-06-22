"""Platform seam for the transparent-mode overlay (input-shape + window hints)."""
from __future__ import annotations
import os
import sys


def overlay_trace(msg: str) -> None:
    """Diagnostic (no-op unless TTMT_OVERLAY_TRACE is set). The overlay layer is
    otherwise silent by convention, which hides why transparent mode fails to
    engage. Writes to stderr so a packaged build can surface the cause."""
    if os.environ.get("TTMT_OVERLAY_TRACE"):
        sys.stderr.write(f"[overlay_trace] {msg}\n")
        sys.stderr.flush()


class OverlayBackend:
    def is_available(self) -> bool: return False
    def set_overlay_hints(self, window) -> None: ...
    def set_initial_state(self, window) -> None: ...
    def set_above(self, window) -> None: ...
    def set_non_activating(self, window) -> None: ...
    def apply_input_region(self, window, region) -> None: ...
    def clear_input_region(self, window) -> None: ...
    def apply_input_shape(self, window, path, dpr: float) -> None: ...


class NoOpOverlayBackend(OverlayBackend):
    """Windows/macOS, or Linux without the X Shape extension."""
    def is_available(self) -> bool: return False


def get_overlay_backend() -> OverlayBackend:
    if sys.platform.startswith("linux"):
        try:
            from utils.overlay.x11_backend import X11OverlayBackend
            backend = X11OverlayBackend()
            if backend.is_available():
                overlay_trace("get_overlay_backend: X11OverlayBackend AVAILABLE")
                return backend
            overlay_trace("get_overlay_backend: X11OverlayBackend NOT available -> NoOp")
        except Exception as e:
            import traceback
            overlay_trace(f"get_overlay_backend: X11 backend raised {e!r} -> NoOp\n"
                          + traceback.format_exc())
    else:
        overlay_trace(f"get_overlay_backend: non-linux ({sys.platform}) -> NoOp")
    return NoOpOverlayBackend()
