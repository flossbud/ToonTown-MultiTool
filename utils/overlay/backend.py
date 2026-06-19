"""Platform seam for the transparent-mode overlay (input-shape + window hints)."""
from __future__ import annotations
import sys


class OverlayBackend:
    def is_available(self) -> bool: return False
    def set_overlay_hints(self, window) -> None: ...
    def apply_input_region(self, window, region) -> None: ...
    def clear_input_region(self, window) -> None: ...


class NoOpOverlayBackend(OverlayBackend):
    """Windows/macOS, or Linux without the X Shape extension."""
    def is_available(self) -> bool: return False


def get_overlay_backend() -> OverlayBackend:
    if sys.platform.startswith("linux"):
        try:
            from utils.overlay.x11_backend import X11OverlayBackend
            backend = X11OverlayBackend()
            if backend.is_available():
                return backend
        except Exception:
            pass
    return NoOpOverlayBackend()
