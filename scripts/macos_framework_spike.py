"""macOS framework-Python provenance spike entrypoint.

Runs BOTH unfrozen (rung 0, executed directly under a python.org framework
python) and frozen (rung 1, inside a PyInstaller .app). Same code path either
way - that isomorphism is the whole point. Logs process provenance, then
delegates the actual gesture to the PROVEN operator spike
(scripts/macos_click_delivery_spike.py) so the delivery path is production-
identical. Operator oracle: with two live TTR toons, point this at the
BACKGROUND toon's window and watch it actuate a click + hover without
foregrounding it.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import platform
import sys
import time

# Run unfrozen as a loose script (python scripts/macos_framework_spike.py): sys.path[0]
# is scripts/, so the repo-root `utils` package isn't importable. Add the repo root.
# Frozen builds bundle `utils`, so this is a no-op there.
if not getattr(sys, "frozen", False):
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)


def _sysconfig_framework():
    import sysconfig
    return sysconfig.get_config_var("PYTHONFRAMEWORK")


def _loaded_libpython_paths():
    """Paths of loaded dyld images whose name mentions Python - the authoritative
    in-process answer to 'which libpython am I running'. Returns a list or None."""
    try:
        libdl = ctypes.CDLL(None)
        libdl._dyld_image_count.restype = ctypes.c_uint32
        libdl._dyld_get_image_name.restype = ctypes.c_char_p
        libdl._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        out = []
        for i in range(libdl._dyld_image_count()):
            name = libdl._dyld_get_image_name(i)
            if name and (b"Python" in name or b"libpython" in name):
                out.append(name.decode("utf-8", "replace"))
        return out or None
    except Exception:
        return None


def _bundle_path():
    try:
        from AppKit import NSBundle
        return str(NSBundle.mainBundle().bundlePath())
    except Exception:
        return None


def provenance() -> dict:
    """Everything needed to prove WHAT process produced an actuation. Safe to call
    before any QApplication exists."""
    return {
        "sys.version": sys.version.split()[0],
        "sys.executable": sys.executable,
        "sys._base_executable": getattr(sys, "_base_executable", None),
        "sys.prefix": sys.prefix,
        "sys.frozen": bool(getattr(sys, "frozen", False)),
        "platform.machine": platform.machine(),
        "platform.architecture": platform.architecture()[0],
        "PYTHONFRAMEWORK": _sysconfig_framework(),
        "libpython": _loaded_libpython_paths(),
        "bundlePath": _bundle_path(),
    }


def format_provenance(info: dict) -> str:
    return "\n".join(f"  {k} = {info[k]!r}" for k in info)


def _log(trace_path: str, text: str) -> None:
    line = f"[spike] {text}"
    print(line, flush=True)
    try:
        with open(os.path.expanduser(trace_path), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _parse_xy(text: str) -> tuple[float, float]:
    """'40,40' -> (40.0, 40.0). Accepts ints or floats, optional spaces."""
    a, b = (p.strip() for p in str(text).split(","))
    return (float(a), float(b))


def screen_point_from_bounds(bounds, win_xy) -> tuple[float, float]:
    """Window-local (wx,wy) -> absolute screen point, given (x,y,w,h) bounds. TTR is
    borderless so kCGWindowBounds is the content rect (production maps the same way)."""
    return (float(bounds[0]) + float(win_xy[0]), float(bounds[1]) + float(win_xy[1]))


def resolve_target(wid, win_xy, pid_opt, screen_opt, trace_path):
    """Fill in pid + screen point from fresh window discovery when not supplied.
    Returns (pid, screen_xy), or (None, None) on failure."""
    from utils import macos_discovery as disc
    pid = pid_opt if pid_opt is not None else disc.get_window_pid(wid)
    if pid is None:
        _log(trace_path, f"could not resolve pid for wid={wid}")
        return None, None
    if screen_opt is not None:
        return int(pid), _parse_xy(screen_opt)
    bounds = disc.get_window_geometry_fresh(wid)
    if not bounds:
        _log(trace_path, f"could not resolve geometry for wid={wid}")
        return None, None
    return int(pid), screen_point_from_bounds(bounds, win_xy)


def run_gesture(pid: int, wid: int, win_xy, screen_xy, trace_path: str) -> int:
    """Drive the PRODUCTION delivery engine (utils.macos_mouse_delivery) directly:
    key_flip + move + down + up (click), then a short hover sweep. Returns 0 on a
    posted click+release, nonzero otherwise. A True from the engine means 'post
    attempted', NOT delivery accepted - the human oracle confirms actuation."""
    from utils.macos_mouse_delivery import MacOSMouseDelivery
    eng = MacOSMouseDelivery()
    if not eng.available:
        _log(trace_path, "delivery engine UNAVAILABLE (SkyLight load failed)")
        return 2
    psn = eng.resolve_psn(wid)
    if psn is None:
        _log(trace_path, f"could not resolve PSN for wid={wid}")
        return 3
    pressed = eng.press(pid, wid, psn, win_xy, screen_xy)
    released = eng.release(pid, wid, psn, win_xy, screen_xy)
    _log(trace_path, f"click press={pressed} release={released}")
    time.sleep(0.4)
    moved = []
    for dx in (0, 12, 24, 12, 0):     # hover sweep so the operator sees rollover
        moved.append(eng.motion(pid, wid, (win_xy[0] + dx, win_xy[1]),
                                (screen_xy[0] + dx, screen_xy[1]), dragging=False))
        time.sleep(0.05)
    _log(trace_path, f"hover sweep moves={moved}")
    return 0 if (pressed and released) else 4


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="Framework-python provenance spike: logs provenance, then drives "
                    "the production delivery engine inside a real QApplication.")
    ap.add_argument("--wid", type=int, help="target (BACKGROUND) toon window id")
    ap.add_argument("--pid", type=int, help="target process id (default: resolve from --wid)")
    ap.add_argument("--win", default="40,40", help="window-local x,y (default 40,40)")
    ap.add_argument("--screen", help="screen x,y override (default: window origin + --win)")
    ap.add_argument("--countdown", type=float, default=5.0,
                    help="seconds before firing, so the operator can focus the "
                         "FOREGROUND toon after launch")
    ap.add_argument("--trace", default="~/ttmt_framework_spike.log")
    ap.add_argument("--provenance-only", action="store_true",
                    help="log provenance and exit 0 (topology gate / relocatability "
                         "smoke test - no gesture, no target needed)")
    ap.add_argument("--list", action="store_true",
                    help="print discovered TTR/CC game windows (wid/pid/bounds) and exit")
    args = ap.parse_args(argv)

    info = provenance()
    _log(args.trace, "PROVENANCE\n" + format_provenance(info))
    if args.provenance_only:
        return 0
    if args.list:
        from utils import macos_discovery as disc
        wins = disc.find_game_windows()        # [(window_id_str, game)]
        if not wins:
            _log(args.trace, "no TTR/CC game windows found (is a toon running?)")
        for wid_str, game in wins:
            _log(args.trace, f"WINDOW game={game} wid={wid_str} "
                             f"pid={disc.get_window_pid(wid_str)} "
                             f"bounds={disc.get_window_geometry(wid_str)}")
        return 0
    if args.wid is None:
        _log(args.trace, "ERROR: --wid is required for a gesture")
        return 64
    win_xy = _parse_xy(args.win)
    pid, screen_xy = resolve_target(args.wid, win_xy, args.pid, args.screen, args.trace)
    if pid is None or screen_xy is None:
        return 65

    # A real QApplication so the process has the production Qt/NSApplication context
    # (the provenance may ride on a live event loop - spec Phase 0 'isomorphic').
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    rc_box = {"rc": 0}

    def fire():
        try:
            rc_box["rc"] = run_gesture(pid, args.wid, win_xy, screen_xy, args.trace)
        except Exception as e:
            _log(args.trace, f"EXCEPTION {e!r}")
            rc_box["rc"] = 70
        app.quit()

    _log(args.trace, f"countdown {args.countdown}s - focus the FOREGROUND toon now")
    QTimer.singleShot(int(args.countdown * 1000), fire)
    app.exec()
    _log(args.trace, f"DONE rc={rc_box['rc']}")
    return rc_box["rc"]


if __name__ == "__main__":
    sys.exit(main())
