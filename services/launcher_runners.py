"""Run the official TTR / CC launchers without an account selected.
Used by the section-header 'Launch TTR/CC Launcher' buttons in the Launch tab.

TTR: prefers `flatpak run com.toontownrewritten.Launcher`. Falls back to
xdg-open on the published .desktop file.
CC: reuses the existing wine_runtimes dispatch path but targets the
TTCCLauncher.exe instead of CorporateClash.exe."""
from __future__ import annotations

import os
import subprocess

from services.wine_runtimes import discover_cc_installs, build_launch_command


_DESKTOP_PATHS = [
    "/var/lib/flatpak/exports/share/applications/com.toontownrewritten.Launcher.desktop",
    os.path.expanduser(
        "~/.local/share/flatpak/exports/share/applications/com.toontownrewritten.Launcher.desktop"
    ),
]


def _flatpak_installed(app_id: str) -> bool:
    try:
        rc = subprocess.run(
            ["flatpak", "info", app_id],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode
    except FileNotFoundError:
        return False
    return rc == 0


def _xdg_open_desktop_file() -> bool:
    for path in _DESKTOP_PATHS:
        if os.path.isfile(path):
            try:
                subprocess.Popen(["xdg-open", path])
                return True
            except FileNotFoundError:
                return False
    return False


def run_official_ttr_launcher() -> bool:
    """Open the official TTR launcher. Returns True if a process was spawned."""
    if _flatpak_installed("com.toontownrewritten.Launcher"):
        try:
            subprocess.Popen(["flatpak", "run", "com.toontownrewritten.Launcher"])
            return True
        except FileNotFoundError:
            pass
    return _xdg_open_desktop_file()


def _cc_launcher_exe_path(install) -> str:
    """Derive TTCCLauncher.exe path from the game exe path.
    CC's launcher binary lives next to the game binary."""
    install_dir = os.path.dirname(install.exe_path)
    return os.path.join(install_dir, "TTCCLauncher.exe")


def run_official_cc_launcher() -> bool:
    """Open the official CC launcher (TTCCLauncher.exe) via the same
    Wine/Bottles/Lutris/Faugus dispatch used for account launches.
    Returns True if a process was spawned."""
    installs = discover_cc_installs()
    if not installs:
        return False
    install = installs[0]
    launcher_path = _cc_launcher_exe_path(install)
    try:
        argv, env_overrides = build_launch_command(
            install, args=[], extra_env={}, target_exe=launcher_path,
        )
    except (ValueError, KeyError):
        return False
    try:
        merged_env = {**os.environ, **env_overrides}
        subprocess.Popen(argv, env=merged_env)
        return True
    except (FileNotFoundError, OSError):
        return False
