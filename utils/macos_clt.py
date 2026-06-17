"""Detect Xcode Command Line Tools WITHOUT triggering the installer. The platform-binary
helper runs `/usr/bin/python3`, an xcode-select shim that prompts to install CLT if no
developer dir is active - so we detect via `xcode-select -p` (exit code) + the resolved
non-shim python path, and NEVER execute /usr/bin/python3 as a probe."""

from __future__ import annotations

import os
import subprocess

# Canonical standalone-CLT install location. `xcode-select --install` always
# populates this path, regardless of which developer dir is currently active.
CLT_DEFAULT_DIR = "/Library/Developer/CommandLineTools"

# Single source of truth for the user-facing CLT-missing reason (consumed by the
# delivery-readiness reasons and the permissions UX). Plain prose, no em-dash.
REASON_CLT_MISSING = "Mouse click sync needs Xcode Command Line Tools"


def _xcode_select_p() -> str | None:
    """Active developer dir, or None. `xcode-select -p` does not trigger the installer."""
    try:
        r = subprocess.run(
            ["/usr/bin/xcode-select", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def _path_executable(p: str | None) -> bool:
    return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)


def _resolved_python(devdir: str) -> str:
    """The non-shim python3 under a developer dir (CLT or full Xcode)."""
    return os.path.join(devdir, "usr", "bin", "python3")


def clt_state() -> tuple[bool, str | None, str | None]:
    """(available: bool, reason: str | None, python_path: str | None). Never runs python3.

    Prefers the active developer dir's python3, then falls back to the canonical
    standalone-CLT location. The fallback matters when the active dir is full Xcode
    (whose bundle may not ship python3 at the dir-relative path): without it the gate
    would false-negative AND the Task 7 `xcode-select --install` remediation would
    dead-end, since installing standalone CLT does not change `xcode-select -p`.
    """
    devdir = _xcode_select_p()
    if not devdir:
        return (False, REASON_CLT_MISSING, None)
    candidates = [_resolved_python(devdir)]
    clt_py = _resolved_python(CLT_DEFAULT_DIR)
    if clt_py not in candidates:
        candidates.append(clt_py)
    for py in candidates:
        if _path_executable(py):
            return (True, None, py)
    return (False, REASON_CLT_MISSING, None)


def open_clt_installer() -> bool:
    """User-INITIATED only: trigger Apple's official Command Line Tools installer GUI.
    (Detection must NEVER run this - it pops a system dialog.) Returns False on failure."""
    try:
        subprocess.Popen(["/usr/bin/xcode-select", "--install"])
        return True
    except Exception:
        return False
