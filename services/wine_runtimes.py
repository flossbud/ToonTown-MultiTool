"""Wine front-end discovery, classification, and launch-command building.

All Linux-Wine specifics live here. Pure logic; no Qt dependencies.
"""

from __future__ import annotations

import glob
import hashlib
import os
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WineInstall:
    """A discovered Corporate Clash installation.

    Attributes
    ----------
    exe_path : str
        Absolute host path to CorporateClash.exe.
    launcher : str
        One of: "bottles", "lutris", "steam-proton", "wine", "native".
    prefix_path : str | None
        Wine prefix root. None for the "native" Windows case.
    display_name : str
        Human-readable label, e.g. "Bottles · Corporate-Clash".
    metadata : dict
        Launcher-specific extras (bottle_name, lutris_game_id, steam_appid,
        runner_path, etc.). Not part of the install signature.
    """

    exe_path: str
    launcher: str
    prefix_path: str | None
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


def install_signature(install: WineInstall) -> str:
    """Return a stable identifier for an install.

    The signature depends only on (launcher, prefix_path, exe_path) realpaths,
    so display_name changes and metadata changes don't invalidate it.
    """
    parts = [
        install.launcher,
        os.path.realpath(install.prefix_path) if install.prefix_path else "",
        os.path.realpath(install.exe_path),
    ]
    raw = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def host_to_windows_path(host_path: str, prefix_path: str) -> str:
    """Translate a host path inside a Wine prefix to its Windows equivalent.

    Example
    -------
    host_path   = "<prefix>/drive_c/users/foo/bar.exe"
    prefix_path = "<prefix>"
    returns     = "C:\\users\\foo\\bar.exe"

    Raises ValueError if host_path is not under prefix_path/drive_c.
    """
    drive_c = os.path.realpath(os.path.join(prefix_path, "drive_c"))
    host_real = os.path.realpath(host_path)
    try:
        rel = os.path.relpath(host_real, drive_c)
    except ValueError as e:
        raise ValueError(
            f"{host_path!r} is not inside {drive_c!r}"
        ) from e
    if rel.startswith(".."):
        raise ValueError(f"{host_path!r} is not inside {drive_c!r}")
    return "C:\\" + rel.replace("/", "\\")


_EXE_NAME = "CorporateClash.exe"


def _native_search_paths() -> list[str]:
    """Return the Windows-native search list. Identical to the old
    CC_ENGINE_SEARCH_PATHS, kept here so the module is self-contained."""
    return [
        os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")),
            "Corporate Clash",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            "Corporate Clash",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
            "Corporate Clash",
        ),
        os.path.expanduser("~/Games/Corporate Clash"),
    ]


def discover_native_windows() -> list[WineInstall]:
    """Return installs reachable via the Windows-native search list.

    Returns an empty list if no install is found. Runs on every platform
    (it is the only non-Wine discovery and is harmless on Linux).
    """
    results: list[WineInstall] = []
    seen: set[str] = set()
    for path in _native_search_paths():
        exe = os.path.join(path, _EXE_NAME)
        if not os.path.isfile(exe):
            continue
        real = os.path.realpath(exe)
        if real in seen:
            continue
        seen.add(real)
        results.append(
            WineInstall(
                exe_path=exe,
                launcher="native",
                prefix_path=None,
                display_name=f"Corporate Clash ({path})",
                metadata={"search_path": path},
            )
        )
    return results


_IN_PREFIX_GLOBS = [
    "drive_c/users/*/AppData/Local/Corporate Clash/CorporateClash.exe",
    "drive_c/Program Files/Corporate Clash/CorporateClash.exe",
    "drive_c/Program Files (x86)/Corporate Clash/CorporateClash.exe",
]


def _find_cc_in_prefix(prefix_path: str) -> list[str]:
    """Return absolute paths to CorporateClash.exe inside a Wine prefix."""
    results: list[str] = []
    for pattern in _IN_PREFIX_GLOBS:
        for match in glob.glob(os.path.join(prefix_path, pattern)):
            if os.path.isfile(match):
                results.append(match)
    return results


def discover_plain_wine() -> list[WineInstall]:
    """Find CC in ~/.wine and ~/.local/share/wineprefixes/*/."""
    if sys.platform == "win32":
        return []
    results: list[WineInstall] = []
    candidates: list[str] = []
    home = os.path.expanduser("~")
    dot_wine = os.path.join(home, ".wine")
    if os.path.isdir(dot_wine):
        candidates.append(dot_wine)
    wineprefixes_root = os.path.join(home, ".local", "share", "wineprefixes")
    if os.path.isdir(wineprefixes_root):
        for entry in sorted(os.listdir(wineprefixes_root)):
            full = os.path.join(wineprefixes_root, entry)
            if os.path.isdir(full):
                candidates.append(full)
    seen: set[str] = set()
    for prefix in candidates:
        for exe in _find_cc_in_prefix(prefix):
            real = os.path.realpath(exe)
            if real in seen:
                continue
            seen.add(real)
            name = os.path.basename(prefix.rstrip(os.sep))
            results.append(
                WineInstall(
                    exe_path=exe,
                    launcher="wine",
                    prefix_path=prefix,
                    display_name=f"Wine · {name}",
                    metadata={"prefix_name": name},
                )
            )
    return results
