"""Re-exec main.py through ./venv/bin/python when the user invoked
TTMT via system Python.

Why: TTMT's runtime PySide6 lives in ./venv (created by install.sh).
Running `python main.py` directly loads the SYSTEM PySide6 instead,
which on some distros (notably current Arch + Python 3.14 + Qt6 6.11.1)
hits a NULL-pointer crash in QFontEngineFT::recalcAdvances during
first-frame text shaping. Routing through the venv interpreter loads
the venv's bundled-Qt PySide6 and sidesteps the entire class of
system-Qt bugs.

Additionally, even with the venv's bundled Qt, ~20-25% of cold launches
on current Arch + Wayland still hit an early-startup font-shaping crash
deep in Qt's event-delivery path (something MultiToonTool.__init__
triggers that minimal harnesses don't reproduce; the bisection isolated
it to that __init__ but not to a specific line). And on Python 3.14 +
PySide6 6.10 we additionally see paint-time GC-vs-Shiboken races (see
project_py314_pyside6_gc_paint_race in agent memory) that the app-level
fixes for x11_discovery/game_registry/ttr_api address but don't fully
preclude. To paper over both classes we supervise the child process:
if it dies via SIGSEGV/SIGBUS/SIGABRT at any point during the session,
we relaunch up to MAX_LAUNCH_ATTEMPTS total. Persistent crashes still
fail loudly once the cap is exhausted; the cap is the safety valve.

This module is intentionally dependency-free (only stdlib) so it can
run before any Qt or PySide6 import.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


# Total launch attempts including the first one. 3 means: original + 2
# retries. Chosen because the empirical cold-launch crash rate is ~25%
# (P(all three fail) = 0.25**3 ≈ 1.5%), and 3 also feels right as a
# session-wide cap for paint-time / GC races: enough to absorb a
# transient blip, few enough that a persistent bug exhausts the budget
# and surfaces to the user instead of silently re-spawning forever.
MAX_LAUNCH_ATTEMPTS = 3

# Exit codes that subprocess returns when the child died via signal.
# Linux: returncode == -signum. Windows doesn't expose SIGBUS/SIGSEGV the
# same way, and `signal.SIGBUS` is simply absent on win32 so a bare
# attribute reference raises AttributeError at module import time. The
# supervisor only triggers on Linux/macOS anyway (the system-Qt crash
# family is Linux-specific), so missing signals are filtered out rather
# than guarded inline.
_RETRYABLE_FATAL_SIGNALS = {
    -sig for sig in (
        getattr(signal, "SIGSEGV", None),
        getattr(signal, "SIGBUS", None),
        getattr(signal, "SIGABRT", None),
    )
    if sig is not None
}


def reexec_into_venv(script_path: str) -> None:
    """Hand off control to ./venv/bin/python with early-crash retry.

    Returns normally (without re-execing) when:

      - TTMT_NO_VENV_REEXEC env var is set (explicit opt-out for users
        who deliberately want to run with system Python)
      - sys.frozen is True (AppImage / PyInstaller / Flatpak bundles ship
        their own self-contained Python; no venv to redirect to)
      - The venv interpreter alongside the script doesn't exist (user
        cloned but hasn't run install.sh yet)
      - We're already running with the venv interpreter (idempotent: no
        infinite re-exec loop on the second pass through main.py)

    When conditions are met, this function spawns the venv interpreter
    as a subprocess and waits for it. If the child exits via a fatal
    signal at any point, the supervisor relaunches it (up to
    MAX_LAUNCH_ATTEMPTS total). When the child finally exits cleanly or
    exhausts the retry budget, the supervisor exits with the same
    returncode and this function never returns.

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
    rc = _supervise_with_retry(venv_python, script_abs, sys.argv[1:])
    sys.exit(rc)


def _supervise_with_retry(venv_python: str, script_abs: str, args: list[str]) -> int:
    """Spawn the venv python repeatedly, retrying on fatal-signal exits
    regardless of when they happen in the session. Returns the final
    returncode (to be passed to sys.exit by the caller). Forwards
    SIGINT/SIGTERM to the child."""
    cmd = [venv_python, script_abs, *args]
    last_rc = 0
    for attempt in range(1, MAX_LAUNCH_ATTEMPTS + 1):
        start = time.monotonic()
        proc = subprocess.Popen(cmd)
        try:
            last_rc = proc.wait()
        except KeyboardInterrupt:
            # Ctrl+C in the supervisor. The child's default handling is to
            # also receive SIGINT (terminal sends it to the whole foreground
            # process group). Wait for it to actually exit before returning.
            try:
                last_rc = proc.wait()
            except KeyboardInterrupt:
                # User hammering Ctrl+C; force-kill and exit.
                proc.kill()
                proc.wait()
                return 130  # standard "killed by SIGINT"
            return last_rc
        elapsed = time.monotonic() - start
        if last_rc == 0:
            return 0
        # Retry on any fatal-signal exit (SIGSEGV/SIGBUS/SIGABRT). The
        # MAX_LAUNCH_ATTEMPTS cap is the safety valve against persistent
        # bugs masquerading as transient flakiness.
        is_fatal_signal = last_rc in _RETRYABLE_FATAL_SIGNALS
        if is_fatal_signal and attempt < MAX_LAUNCH_ATTEMPTS:
            sig_name = signal.Signals(-last_rc).name
            print(
                f"[ttmt] Fatal-signal exit ({sig_name} after {elapsed:.1f}s); "
                f"retrying ({attempt}/{MAX_LAUNCH_ATTEMPTS - 1}).",
                file=sys.stderr,
            )
            continue
        # Clean failure, exhausted retries, or non-retryable signal:
        # propagate to the user.
        return last_rc
    return last_rc
