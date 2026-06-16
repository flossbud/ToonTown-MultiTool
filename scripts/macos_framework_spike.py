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
