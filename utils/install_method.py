"""Detect how the running app was installed. Cached process-wide.
Used by update_runner to dispatch the right update action.
"""
from __future__ import annotations

import os
import subprocess
import sys
from enum import Enum
from typing import Optional


_FLATPAK_MARKER = "/.flatpak-info"
_ARCH_MARKER = "/etc/arch-release"


class InstallMethod(Enum):
    WINDOWS_INSTALLER = "windows_installer"
    APPIMAGE = "appimage"
    FLATPAK = "flatpak"
    AUR = "aur"
    DEB = "deb"
    SOURCE = "source"


_cached: Optional[InstallMethod] = None


def detect() -> InstallMethod:
    global _cached
    if _cached is not None:
        return _cached
    _cached = _detect_uncached()
    return _cached


def _detect_uncached() -> InstallMethod:
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        return InstallMethod.WINDOWS_INSTALLER

    if os.environ.get("APPIMAGE"):
        return InstallMethod.APPIMAGE

    if os.environ.get("FLATPAK_ID") or os.path.exists(_FLATPAK_MARKER):
        return InstallMethod.FLATPAK

    exec_path = sys.executable

    if os.path.exists(_ARCH_MARKER):
        try:
            r = subprocess.run(
                ["pacman", "-Qo", exec_path],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and ("ttmt" in r.stdout or "ttmt-beta" in r.stdout):
                return InstallMethod.AUR
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    try:
        r = subprocess.run(
            ["dpkg", "-S", exec_path],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return InstallMethod.DEB
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    return InstallMethod.SOURCE


def _reset_cache_for_tests() -> None:
    """Test-only: clear the module cache. Not public API."""
    global _cached
    _cached = None
