"""Run the official TTR / CC launchers without an account selected.
Used by the section-header 'Launch TTR/CC Launcher' buttons in the Launch tab.

TTR: prefers `flatpak run com.toontownrewritten.Launcher`. Falls back to
xdg-open on the published .desktop file.
CC: reuses the existing wine_runtimes dispatch path but targets the
TTCCLauncher.exe instead of CorporateClash.exe."""
from __future__ import annotations

import glob
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


# Launcher binary names, in preference order. Modern CC ships as
# `new_launcher.exe`; `TTCCLauncher.exe` is the pre-rename legacy name we
# still see on older installs.
_CC_LAUNCHER_NAMES = ("new_launcher.exe", "TTCCLauncher.exe")

# Standard Wine-prefix locations to probe. CC's launcher and game live in
# DIFFERENT subtrees (launcher in Program Files, game in
# users/<u>/AppData/Local), so deriving the launcher path from the game
# dirname misses the common case.
_CC_LAUNCHER_PREFIX_GLOBS = (
    "drive_c/Program Files/Corporate Clash/{name}",
    "drive_c/Program Files (x86)/Corporate Clash/{name}",
    "drive_c/users/*/AppData/Local/Corporate Clash/{name}",
)


def _cc_launcher_exe_path(install) -> str | None:
    """Locate the CC launcher .exe inside the install's Wine prefix.

    Tries the modern `new_launcher.exe` first, falls back to legacy
    `TTCCLauncher.exe`. Searches the standard Wine-prefix subtrees, then
    the game's own directory as a last resort for unusual co-located
    installs. Returns None when no binary is found, in which case the
    caller should treat the launch as failed.
    """
    candidates: list[str] = []
    prefix = install.prefix_path
    if prefix:
        for name in _CC_LAUNCHER_NAMES:
            for tpl in _CC_LAUNCHER_PREFIX_GLOBS:
                pattern = os.path.join(prefix, tpl.format(name=name))
                candidates.extend(glob.glob(pattern))
    install_dir = os.path.dirname(install.exe_path)
    for name in _CC_LAUNCHER_NAMES:
        candidates.append(os.path.join(install_dir, name))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


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
    if launcher_path is None:
        return False
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
