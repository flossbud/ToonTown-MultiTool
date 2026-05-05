"""Open external URLs from a packaged build without poisoning the child env.

PyInstaller's onefile bootloader sets LD_LIBRARY_PATH (and LD_PRELOAD) to its
extraction dir so the bundled libs load. When Qt's QDesktopServices.openUrl
fork+execs xdg-open, the helper inherits those values and tries to load the
bundled libstdc++ / libQt6* against the system's KF6/Qt6 libs, which fails
with `GLIBCXX_*` and `Qt_*_PRIVATE_API` symbol errors. The link silently
no-ops.

PyInstaller saves the host values as `<VAR>_ORIG` siblings precisely so child
processes can be re-pointed at the host environment. This module restores
those before exec'ing xdg-open. Inside Flatpak we route through host_popen,
which already strips the same vars when proxying via flatpak-spawn.

On Windows and macOS Qt's openUrl works fine (no LD_* injection), so we
delegate there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from utils.host_spawn import host_popen, in_flatpak


_LD_VARS = ("LD_LIBRARY_PATH", "LD_PRELOAD")


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ with PyInstaller's LD_* overrides reverted.

    Only mutates the env when running from a frozen bundle. In dev mode the
    user's LD_LIBRARY_PATH (if any) is theirs to keep.
    """
    env = os.environ.copy()
    if not getattr(sys, "frozen", False):
        return env
    for var in _LD_VARS:
        orig_key = f"{var}_ORIG"
        if orig_key in env:
            env[var] = env[orig_key]
        else:
            env.pop(var, None)
        env.pop(orig_key, None)
    return env


def open_url(url: str) -> bool:
    """Open `url` in the user's default browser. Returns True on a successful spawn."""
    if not url:
        return False

    if sys.platform.startswith("linux"):
        try:
            if in_flatpak():
                host_popen(["xdg-open", url])
                return True
            xdg = shutil.which("xdg-open") or "xdg-open"
            subprocess.Popen(
                [xdg, url],
                env=_clean_env(),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            pass  # fall through to Qt as a last resort

    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
    except ImportError:
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))
