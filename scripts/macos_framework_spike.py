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


def _ensure_operator_spike_importable() -> None:
    """Put the scripts/ dir on sys.path so the PROVEN operator spike imports
    whether we run unfrozen (from the repo) or frozen (bundled alongside)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    # Frozen: PyInstaller unpacks bundled sources under sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for sub in (meipass, os.path.join(meipass, "scripts")):
            if sub not in sys.path:
                sys.path.insert(0, sub)


def run_delegated_gesture(passthrough_argv: list[str]) -> int:
    """Drive the real delivery path by calling the operator spike's main() with a
    gesture subcommand (e.g. ['sl-gesture', '--wid', '123', ...]). Returns its rc."""
    _ensure_operator_spike_importable()
    import macos_click_delivery_spike as opspike
    return int(opspike.main(passthrough_argv))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="Framework-python provenance spike: logs provenance, then runs "
                    "the proven operator gesture inside a real QApplication.")
    ap.add_argument("--countdown", type=float, default=5.0,
                    help="seconds before firing, so the operator can focus the "
                         "FOREGROUND toon after launch")
    ap.add_argument("--trace", default="~/ttmt_framework_spike.log")
    ap.add_argument("--provenance-only", action="store_true",
                    help="log provenance and exit 0 (used by the topology gate / "
                         "relocatability smoke test - no gesture, no target needed)")
    args, passthrough = ap.parse_known_args(argv)

    info = provenance()
    _log(args.trace, "PROVENANCE\n" + format_provenance(info))

    if args.provenance_only:
        return 0

    # A real QApplication so the process has the production Qt/NSApplication context
    # (the provenance may ride on a live event loop - spec Phase 0 'isomorphic').
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    rc_box = {"rc": 0}

    def fire():
        _log(args.trace, f"FIRE passthrough={passthrough!r}")
        try:
            rc_box["rc"] = run_delegated_gesture(passthrough)
        except SystemExit as e:           # argparse inside the operator spike
            rc_box["rc"] = int(e.code or 0)
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
