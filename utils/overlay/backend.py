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
    def set_skip_close_animation(self, window) -> None: ...
    def set_rep_initial_state(self, window) -> None: ...
    def set_window_opacity(self, window, opacity: float) -> None: ...

    def wants_taskbar_rep(self) -> bool:
        """Whether the controller should build the aligned-mirror taskbar
        representative while floating. True on X11 (a DOCK cluster cannot be
        taskbar-listed on KWin, so the rep stands in); False on Windows,
        where the cluster window itself carries the taskbar identity."""
        return True


class NoOpOverlayBackend(OverlayBackend):
    """Unsupported platform, opted-out backend, or Linux without X Shape."""
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
    elif sys.platform == "win32":
        # Escape hatch: TTMT_OVERLAY_WIN32 set to a falsey token disables the
        # Windows backend entirely (Float UI reverts to unavailable/inert).
        raw = os.environ.get("TTMT_OVERLAY_WIN32")
        if raw is not None and raw.strip().lower() in {"0", "no", "n", "false", "f", "off"}:
            overlay_trace("get_overlay_backend: TTMT_OVERLAY_WIN32 opt-out -> NoOp")
            return NoOpOverlayBackend()
        try:
            from utils.overlay.win32_backend import Win32OverlayBackend
            backend = Win32OverlayBackend()
            if backend.is_available():
                overlay_trace("get_overlay_backend: Win32OverlayBackend AVAILABLE")
                return backend
            overlay_trace("get_overlay_backend: Win32OverlayBackend NOT available -> NoOp")
        except Exception as e:
            import traceback
            overlay_trace(f"get_overlay_backend: win32 backend raised {e!r} -> NoOp\n"
                          + traceback.format_exc())
    elif sys.platform == "darwin":
        # Escape hatch: TTMT_OVERLAY_MACOS set to a falsey token disables the
        # macOS backend entirely (Float UI reverts to unavailable/inert).
        raw = os.environ.get("TTMT_OVERLAY_MACOS")
        if raw is not None and raw.strip().lower() in {"0", "no", "n", "false", "f", "off"}:
            overlay_trace("get_overlay_backend: TTMT_OVERLAY_MACOS opt-out -> NoOp")
            return NoOpOverlayBackend()
        try:
            from utils.overlay.macos_backend import MacOSOverlayBackend
            backend = MacOSOverlayBackend()
            if backend.is_available():
                overlay_trace("get_overlay_backend: MacOSOverlayBackend AVAILABLE")
                return backend
            overlay_trace("get_overlay_backend: MacOSOverlayBackend NOT available -> NoOp")
        except Exception as e:
            import traceback
            overlay_trace(f"get_overlay_backend: macos backend raised {e!r} -> NoOp\n"
                          + traceback.format_exc())
    else:
        overlay_trace(f"get_overlay_backend: unsupported platform ({sys.platform}) -> NoOp")
    return NoOpOverlayBackend()
