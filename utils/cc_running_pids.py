"""Scan /proc for CC processes whose WINEPREFIX matches a given prefix.

Used by the isolation toggle's UI to show a "Restart these CC windows
for the change to take effect" notice after rewriting preferences.json.
Non-fatal -- TTMT does not kill any processes.
"""

from __future__ import annotations

import os
from pathlib import Path


_WINE_PRELOADER_BASENAMES = {"wine-preloader", "wine64-preloader"}
_PROTON_WINE_MARKER = "/files/lib/wine/"


def _iter_wine_pids():
    """Yield every PID whose /proc/<pid>/exe is a wine preloader."""
    proc = Path("/proc")
    if not proc.exists():
        return
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            target = os.readlink(entry / "exe")
        except OSError:
            continue
        basename = os.path.basename(target)
        if basename in _WINE_PRELOADER_BASENAMES or _PROTON_WINE_MARKER in target:
            yield int(entry.name)


def _read_wineprefix_env(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    for item in raw.split(b"\0"):
        if item.startswith(b"WINEPREFIX="):
            return item[len(b"WINEPREFIX="):].decode("utf-8", "replace")
    return None


def _read_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace")


def _normalize(path: str) -> str:
    return path.rstrip("/").rstrip("\\")


def scan_for_prefix(prefix: str) -> list[int]:
    """Return PIDs running CC under the given WINEPREFIX.

    A PID counts as CC if its cmdline contains 'CorporateClash' (the .exe
    name CC ships with).
    """
    target = _normalize(prefix)
    found = []
    for pid in _iter_wine_pids():
        wp = _read_wineprefix_env(pid)
        if wp is None or _normalize(wp) != target:
            continue
        cmd = _read_cmdline(pid)
        if "CorporateClash" not in cmd:
            continue
        found.append(pid)
    return found
