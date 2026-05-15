"""Wine front-end discovery, classification, and launch-command building.

All Linux-Wine specifics live here. Pure logic; no Qt dependencies.
"""

from __future__ import annotations

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
