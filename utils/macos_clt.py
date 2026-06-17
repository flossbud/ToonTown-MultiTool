"""Detect Xcode Command Line Tools WITHOUT triggering the installer. The platform-binary
helper runs `/usr/bin/python3`, an xcode-select shim that prompts to install CLT if no
developer dir is active - so we detect via `xcode-select -p` (exit code) + the resolved
non-shim python path, and NEVER execute /usr/bin/python3 as a probe."""

import os
import subprocess


def _xcode_select_p():
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


def _path_executable(p) -> bool:
    return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)


def _resolved_python(devdir: str) -> str:
    # CLT: <devdir>/usr/bin/python3 ; full Xcode: <devdir>/usr/bin/python3 also resolves.
    return os.path.join(devdir, "usr", "bin", "python3")


def clt_state():
    """(available: bool, reason: str | None, python_path: str | None). Never runs python3."""
    devdir = _xcode_select_p()
    if not devdir:
        return (False, "Mouse click sync needs Xcode Command Line Tools", None)
    py = _resolved_python(devdir)
    if not _path_executable(py):
        return (False, "Mouse click sync needs Xcode Command Line Tools", None)
    return (True, None, py)
