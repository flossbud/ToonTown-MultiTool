"""Re-exec main.py through ./venv/bin/python when the user invoked
TTMT via system Python.

Why: TTMT's runtime PySide6 lives in ./venv (created by install.sh).
Running `python main.py` directly loads the SYSTEM PySide6 instead,
which on some distros (notably current Arch + Python 3.14 + Qt6 6.11.1)
hits a NULL-pointer crash in QFontEngineFT::recalcAdvances during
first-frame text shaping. Routing through the venv interpreter loads
the venv's bundled-Qt PySide6 and sidesteps the entire class of
system-Qt bugs.

This module is intentionally dependency-free (only stdlib) so it can
run before any Qt or PySide6 import.
"""
from __future__ import annotations

import os
import sys


def reexec_into_venv(script_path: str) -> None:
    """Replace the current process with one running ./venv/bin/python
    when conditions are met. Returns normally (without re-execing) when:

      - TTMT_NO_VENV_REEXEC env var is set (explicit opt-out for users
        who deliberately want to run with system Python)
      - sys.frozen is True (AppImage / PyInstaller / Flatpak bundles ship
        their own self-contained Python; no venv to redirect to)
      - The venv interpreter alongside the script doesn't exist (user
        cloned but hasn't run install.sh yet)
      - We're already running with the venv interpreter (idempotent: no
        infinite re-exec loop on the second pass through main.py)

    On successful exec, this function does NOT return (the current
    process is replaced).

    script_path: the absolute or relative path to main.py. Used for
        two purposes: locating ./venv relative to it, and re-passing
        it as the script argument to the new process.
    """
    if os.environ.get("TTMT_NO_VENV_REEXEC"):
        return
    if getattr(sys, "frozen", False):
        return
    # If we're already in any venv (the project's ./venv or one the user
    # activated for their own testing), trust them and don't redirect.
    # Python sets sys.prefix to the venv root when running through a
    # venv's interpreter, and sys.base_prefix to the original install
    # location -- comparing them is the canonical "am I in a venv" test.
    # Realpath comparison on sys.executable is unsafe because ./venv/bin/python
    # is typically a symlink to the system python; both resolve to the same
    # binary, but the venv-launched process has a different sys.prefix and
    # site-packages search path.
    if sys.prefix != sys.base_prefix:
        return
    script_abs = os.path.abspath(script_path)
    here = os.path.dirname(script_abs)
    if sys.platform == "win32":
        venv_python = os.path.join(here, "venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(here, "venv", "bin", "python")
    if not os.path.isfile(venv_python):
        return
    # Replace the current process. Does not return on success. On
    # failure (e.g. venv_python exists but isn't executable), os.execv
    # raises OSError -- let it propagate so the user sees a clear
    # traceback rather than silently falling through to the broken
    # system-Python path.
    os.execv(venv_python, [venv_python, script_abs, *sys.argv[1:]])
