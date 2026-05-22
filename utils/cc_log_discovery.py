"""CC log file discovery.

When TTMT spawned CC itself, the stdout path is in cc_launcher's registry.
When CC was launched externally (Steam/Proton, Lutris, Bottles, Faugus,
manual Wine, native Windows), CC still writes its own log file under
<AppData>/Corporate Clash/logs/corporateclash-{date}.log. This module
finds that file for a given PID.

Three layers, tried in order:
  1. psutil open_files() -- per-PID accurate, cross-platform.
  2. Wine-prefix glob (Linux: /proc/$PID/environ WINEPREFIX, else ~/.wine;
     Windows: %LOCALAPPDATA%). mtime correlation to the process create_time.
  3. Manual scan of a user-configured directory.

If manual_dir is set, it applies as a scope filter (Layers 1, 2) or
scan target (Layer 3) so the user's "search only here" intent is
honored uniformly.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# Matches absolute paths to CC's own log files under any prefix layout.
_CC_LOG_RE = re.compile(
    r".*[/\\]Corporate Clash[/\\]logs[/\\][^/\\]+\.log$",
    re.IGNORECASE,
)


def _is_cc_log_path(path_str: str) -> bool:
    return bool(_CC_LOG_RE.match(path_str))


def _is_inside(path: Path, scope: Path) -> bool:
    try:
        path.resolve().relative_to(scope.resolve())
        return True
    except (ValueError, OSError):
        return False


def _layer1_psutil(pid: int, manual_dir: Optional[Path]) -> Optional[Path]:
    """Return the CC log file path that PID has open, or None."""
    try:
        proc = psutil.Process(pid)
        files = proc.open_files()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.warning("[cc_log_discovery] L1 psutil failed for pid=%d: %s", pid, exc)
        return None
    for f in files:
        if not _is_cc_log_path(f.path):
            continue
        candidate = Path(f.path)
        if manual_dir is not None and not _is_inside(candidate, manual_dir):
            continue
        return candidate
    return None


# Process name that identifies a real CC process on the host. Case-insensitive
# substring match against the process's `name` attribute. Robust across
# launchers because every Wine/Proton wrapper eventually exec's the actual
# binary, and that binary's process name is "CorporateClash.exe" regardless
# of how it was started.
_CC_PROCESS_NAME_NEEDLE = "corporateclash"


def _layer1_5_process_scan(manual_dir: Optional[Path]) -> Optional[Path]:
    """When the input PID doesn't yield a CC log (typical of sandboxed
    launchers like Faugus/Bottles/Proton, where the X11 _NET_WM_PID points
    into a different PID namespace than the host), scan host processes for
    one whose name matches CorporateClash.exe and run Layer 1 against it.

    Returns the first matching log path. Multi-instance external CC is
    best-effort and may return the wrong instance's log; documented in the
    spec.
    """
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if _CC_PROCESS_NAME_NEEDLE not in name:
                continue
            path = _layer1_psutil(proc.info["pid"], manual_dir)
            if path is not None:
                return path
        except psutil.Error as exc:
            logger.debug("[cc_log_discovery] L1.5 skipping pid: %s", exc)
            continue
    return None


def _read_proc_environ(pid: int) -> bytes:
    """Return /proc/$PID/environ on Linux, or b'' on failure / non-Linux."""
    if sys.platform != "linux":
        return b""
    try:
        return Path(f"/proc/{pid}/environ").read_bytes()
    except (OSError, FileNotFoundError):
        return b""


def _proc_create_time(pid: int) -> float:
    """Return the process create time, or 0.0 on failure."""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def _wineprefix_from_environ(environ_bytes: bytes) -> Optional[Path]:
    """Extract WINEPREFIX from a /proc/$PID/environ blob (NUL-separated)."""
    for entry in environ_bytes.split(b"\x00"):
        if entry.startswith(b"WINEPREFIX="):
            value = entry[len(b"WINEPREFIX="):].decode("utf-8", errors="replace")
            if value:
                return Path(value)
    return None


def _candidate_logs_dirs(pid: int, manual_dir: Optional[Path]) -> list[Path]:
    """Return the list of directories to glob, in priority order."""
    if manual_dir is not None:
        return [manual_dir]
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return [Path(local_appdata) / "Corporate Clash" / "logs"]
        return []
    # Linux: try WINEPREFIX from process environ, fall back to ~/.wine.
    environ = _read_proc_environ(pid)
    prefix = _wineprefix_from_environ(environ)
    dirs: list[Path] = []
    if prefix is not None:
        dirs.append(prefix / "drive_c" / "users")
    dirs.append(Path.home() / ".wine" / "drive_c" / "users")
    # Expand: <root>/<user>/AppData/Local/Corporate Clash/logs for any user.
    expanded: list[Path] = []
    for root in dirs:
        if not root.exists():
            continue
        for user_dir in root.iterdir():
            candidate = user_dir / "AppData" / "Local" / "Corporate Clash" / "logs"
            if candidate.is_dir():
                expanded.append(candidate)
    return expanded


def _layer2_prefix(pid: int, manual_dir: Optional[Path]) -> Optional[Path]:
    create_time = _proc_create_time(pid)
    best: Optional[Path] = None
    best_mtime = 0.0
    for logs_dir in _candidate_logs_dirs(pid, manual_dir):
        for log_path in logs_dir.glob("*.log"):
            try:
                mtime = log_path.stat().st_mtime
            except OSError:
                continue
            if mtime < create_time:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best = log_path
    return best


def _layer3_manual_dir(manual_dir: Optional[Path]) -> Optional[Path]:
    if manual_dir is None or not manual_dir.is_dir():
        return None
    best: Optional[Path] = None
    best_mtime = 0.0
    for log_path in manual_dir.glob("*.log"):
        try:
            mtime = log_path.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = log_path
    return best


def find_log_for_pid(
    pid: int,
    manual_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve the CC log file path for the given PID.

    Tries Layer 1 (psutil), then Layer 1.5 (host process-name scan,
    needed when the input PID is a sandbox alias and doesn't match the
    real CC process on the host), then Layer 2 (prefix glob), then
    Layer 3 (manual_dir scan, only if manual_dir is set). Returns None
    if all fail.

    Multi-instance external CC caveat: if the input PID is a sandbox
    alias and Layer 1.5 fires, the returned log may belong to a
    different CC instance than the one the caller meant. Single-instance
    external CC is unambiguous; multi-instance Steam/Proton/Bottles
    setups are best-effort.
    """
    path = _layer1_psutil(pid, manual_dir)
    if path is not None:
        return path
    path = _layer1_5_process_scan(manual_dir)
    if path is not None:
        return path
    path = _layer2_prefix(pid, manual_dir)
    if path is not None:
        return path
    path = _layer3_manual_dir(manual_dir)
    if path is not None:
        return path
    return None
