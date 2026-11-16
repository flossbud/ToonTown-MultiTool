"""Startup UI scale: fit the fixed-size window design onto small screens.

The main window's content has a hard minimum of roughly 856x843 logical
pixels (the Multitoon pinwheel). Logical pixels are what is left after the OS
display scale, so a 1920x1080 laptop at Windows' default 150% offers only
1280x720 of them and the window came out TALLER THAN THE SCREEN. Clamping the
window height cannot help: the content minimum wins.

Qt can only scale a widget UI as a whole, and only if it is told before the
QApplication exists (QT_SCALE_FACTOR). So this module measures the primary
screen with native calls, before Qt starts, and picks the largest scale at
which the design fits. Screens the design already fits on are left alone.

Controls:
  TTMT_UI_SCALE=off     never scale
  TTMT_UI_SCALE=0.8     force a scale
A QT_SCALE_FACTOR / QT_SCREEN_SCALE_FACTORS the user set themselves wins.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Callable, NamedTuple

# The window's default size (main.py) and the breathing room clamp_window_height
# keeps around it.
DESIGN_W = 880
DESIGN_H = 862
MARGIN = 48

MIN_SCALE = 0.6      # below this text gets too small; a tight fit is better
STEP = 0.05          # quantized so nearly-equal screens render identically

ENV_OVERRIDE = "TTMT_UI_SCALE"
# Set by us, never by the user: the scale in effect, handed to our own helper
# processes. QT_SCALE_FACTOR itself is removed from the environment once Qt
# has read it so that launched games and launchers do not inherit it.
ENV_ACTIVE = "TTMT_UI_SCALE_ACTIVE"
_QT_VAR = "QT_SCALE_FACTOR"
_USER_QT_VARS = ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS")


class ScaleDecision(NamedTuple):
    scale: float
    reason: str

    def stamp(self) -> str:
        return f"[UIScale] scale={self.scale:.2f} ({self.reason})"


def compute_ui_scale(avail_w: float, avail_h: float) -> float:
    """Largest scale (<= 1.0) at which the design fits in the given usable
    logical screen size, quantized down to STEP and floored at MIN_SCALE."""
    if avail_w <= 0 or avail_h <= 0:
        return 1.0
    fit = min((avail_h - MARGIN) / DESIGN_H, (avail_w - MARGIN) / DESIGN_W)
    if fit >= 1.0:
        return 1.0
    stepped = math.floor(fit / STEP + 1e-9) * STEP
    return round(max(MIN_SCALE, stepped), 2)


# ── Native probes (must not create a QGuiApplication) ──────────────────────

def logical_size_win32(phys_w: int, phys_h: int, scale_pct: int,
                       monitor_h: int, work_h: int,
                       monitor_w: int = 0, work_w: int = 0) -> tuple[float, float]:
    """Usable logical size from pieces that are each independent of the
    process's DPI awareness: the physical mode, the display scale percent, and
    the work-area/monitor RATIO (both rects come from one call, so whatever
    coordinate space they are in cancels out)."""
    factor = max(scale_pct, 100) / 100.0
    h_ratio = (work_h / monitor_h) if monitor_h > 0 and 0 < work_h <= monitor_h else 1.0
    w_ratio = (work_w / monitor_w) if monitor_w > 0 and 0 < work_w <= monitor_w else 1.0
    return (phys_w / factor * w_ratio, phys_h / factor * h_ratio)


def _probe_win32() -> tuple[float, float] | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(None, -1, ctypes.byref(mode)):   # ENUM_CURRENT_SETTINGS
        return None
    phys_w, phys_h = int(mode.dmPelsWidth), int(mode.dmPelsHeight)

    # DEVICE_PRIMARY = 0. Returns the display scale percent (100, 125, 150 ...).
    scale_pct = int(ctypes.windll.shcore.GetScaleFactorForDevice(0))
    if scale_pct < 100:
        return None

    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)             # DEFAULTTOPRIMARY
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    mon_w = mon_h = work_w = work_h = 0
    if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        mon_w = info.rcMonitor.right - info.rcMonitor.left
        mon_h = info.rcMonitor.bottom - info.rcMonitor.top
        work_w = info.rcWork.right - info.rcWork.left
        work_h = info.rcWork.bottom - info.rcWork.top
    return logical_size_win32(phys_w, phys_h, scale_pct, mon_h, work_h, mon_w, work_w)


def _probe_darwin() -> tuple[float, float] | None:
    from AppKit import NSScreen
    screens = NSScreen.screens()
    if not screens:
        return None
    frame = screens[0].visibleFrame()        # points == Qt logical pixels
    return (float(frame.size.width), float(frame.size.height))


def xft_dpi_from_resources(resources: str) -> float | None:
    """Parse `Xft.dpi` out of an X RESOURCE_MANAGER string."""
    for line in resources.splitlines():
        name, _, value = line.partition(":")
        if name.strip() == "Xft.dpi":
            try:
                dpi = float(value.strip())
            except ValueError:
                return None
            return dpi if dpi > 0 else None
    return None


def _probe_x11() -> tuple[float, float] | None:
    from Xlib import X, Xatom, display
    d = display.Display()
    try:
        screen = d.screen()
        root = screen.root
        w_px, h_px = screen.width_in_pixels, screen.height_in_pixels

        # Primary monitor, when RandR can tell us; the X screen spans them all.
        try:
            primary = root.xrandr_get_output_primary().output
            res = root.xrandr_get_screen_resources()
            if primary:
                info = d.xrandr_get_output_info(primary, res.config_timestamp)
                if info.crtc:
                    crtc = d.xrandr_get_crtc_info(info.crtc, res.config_timestamp)
                    if crtc.width and crtc.height:
                        w_px, h_px = crtc.width, crtc.height
        except Exception:
            pass

        # Panels: _NET_WORKAREA is x, y, w, h per desktop for the whole X
        # screen, so it can only ever shrink the primary monitor's size.
        try:
            prop = root.get_full_property(d.intern_atom("_NET_WORKAREA"), Xatom.CARDINAL)
            if prop is not None and len(prop.value) >= 4:
                w_px = min(w_px, int(prop.value[2]))
                h_px = min(h_px, int(prop.value[3]))
        except Exception:
            pass

        # Qt's xcb plugin scales by Xft.dpi / 96.
        dpr = 1.0
        try:
            prop = root.get_full_property(Xatom.RESOURCE_MANAGER, X.AnyPropertyType)
            if prop is not None:
                raw = prop.value
                text = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
                dpi = xft_dpi_from_resources(text)
                if dpi:
                    dpr = max(1.0, dpi / 96.0)
        except Exception:
            pass
        return (w_px / dpr, h_px / dpr)
    finally:
        d.close()


def probe_available_logical_size(platform: str = sys.platform) -> tuple[float, float] | None:
    """Usable size of the primary screen in Qt logical pixels, or None when
    it cannot be measured (in which case nothing is scaled)."""
    try:
        if platform == "win32":
            return _probe_win32()
        if platform == "darwin":
            return _probe_darwin()
        if platform.startswith("linux"):
            return _probe_x11()
    except Exception:
        return None
    return None


# ── Startup entry points ───────────────────────────────────────────────────

def _parse_scale(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if 0.3 <= value <= 3.0 else None


def apply_startup_ui_scale(
    environ=os.environ,
    platform: str = sys.platform,
    probe: Callable[[str], tuple[float, float] | None] = probe_available_logical_size,
) -> ScaleDecision:
    """Decide the UI scale and export it for Qt. Call BEFORE the QApplication
    is created; follow with release_qt_env() once it exists."""
    inherited = _parse_scale(environ.get(ENV_ACTIVE, ""))
    if inherited is not None:
        # A helper process started by a scaled parent: match it exactly.
        environ[_QT_VAR] = f"{inherited:g}"
        return ScaleDecision(inherited, "inherited from parent")

    for var in _USER_QT_VARS:
        if environ.get(var):
            return ScaleDecision(1.0, f"left to {var} from the environment")

    override = environ.get(ENV_OVERRIDE, "").strip().lower()
    if override in ("off", "0", "no", "false", "1", "1.0"):
        return ScaleDecision(1.0, f"{ENV_OVERRIDE}={override}")
    if override and override != "auto":
        forced = _parse_scale(override)
        if forced is None:
            return ScaleDecision(1.0, f"ignored bad {ENV_OVERRIDE}={override!r}")
        environ[_QT_VAR] = f"{forced:g}"
        environ[ENV_ACTIVE] = f"{forced:g}"
        return ScaleDecision(forced, f"{ENV_OVERRIDE}={override}")

    # The Linux probe speaks X11, which is what Qt uses here by default (xcb,
    # including under XWayland). On any other Qt platform its numbers would
    # not be the ones Qt lays out with, so do not guess.
    qt_platform = environ.get("QT_QPA_PLATFORM", "").split(":")[0].strip().lower()
    if platform.startswith("linux") and qt_platform not in ("", "xcb"):
        return ScaleDecision(1.0, f"not measured on the {qt_platform} Qt platform")

    size = probe(platform)
    if size is None:
        return ScaleDecision(1.0, "screen size unknown")
    scale = compute_ui_scale(*size)
    where = f"usable screen {size[0]:.0f}x{size[1]:.0f}"
    if scale >= 1.0:
        return ScaleDecision(1.0, f"{where} fits the {DESIGN_W}x{DESIGN_H} window")
    environ[_QT_VAR] = f"{scale:g}"
    environ[ENV_ACTIVE] = f"{scale:g}"
    return ScaleDecision(scale, f"{where} is too small for the {DESIGN_W}x{DESIGN_H} window")


def release_qt_env(environ=os.environ) -> None:
    """Call once the QApplication exists. Qt has read QT_SCALE_FACTOR by then;
    dropping it keeps games and launchers we start from inheriting our scale.
    ENV_ACTIVE stays so our own helper processes can match."""
    if environ.get(ENV_ACTIVE):
        environ.pop(_QT_VAR, None)
