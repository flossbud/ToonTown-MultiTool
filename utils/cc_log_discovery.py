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


def find_log_for_pid(
    pid: int,
    manual_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve the CC log file path for the given PID.

    Tries Layer 1 (psutil), then Layer 2 (prefix glob), then Layer 3
    (manual_dir scan, only if manual_dir is set). Returns None if all
    fail.
    """
    path = _layer1_psutil(pid, manual_dir)
    if path is not None:
        return path
    return None
