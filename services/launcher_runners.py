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


def run_official_cc_launcher(settings_manager=None) -> bool:
    """Open the official CC launcher (TTCCLauncher.exe) via the same
    Wine/Bottles/Lutris/Faugus/Steam-Proton dispatch used for account
    launches. Returns True if a process was spawned.

    When settings_manager is provided, the install matching
    CC_ENGINE_INSTALL_SIGNATURE is used. When multiple installs are
    detected and no signature is stored (or it doesn't match any
    discovered install), returns False so the caller can prompt the
    install picker. Pass None for backward-compatible single-install
    behavior."""
    installs = discover_cc_installs()
    if not installs:
        return False

    install = _select_install(installs, settings_manager)
    if install is None:
        return False

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


def _select_install(installs, settings_manager):
    """Resolve which install to use.

    - 1 install: use it (regardless of stored signature).
    - Multiple installs + settings_manager provided + stored signature matches one: use that.
    - Multiple installs + no settings_manager: use first (backward compat).
    - Multiple installs + settings_manager but no match: return None (caller should prompt picker).
    """
    if len(installs) == 1:
        return installs[0]
    if settings_manager is None:
        return installs[0]
    from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE
    from services.wine_runtimes import install_signature
    stored = settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
    if not stored:
        return None
    for i in installs:
        if install_signature(i) == stored:
            return i
    return None
