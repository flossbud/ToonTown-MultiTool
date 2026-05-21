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
it to that __init__ but not to a specific line). To paper over that
flakiness we supervise the child process: if it dies via SIGSEGV/SIGBUS/
SIGABRT within the first ~3 seconds, we relaunch up to MAX_RETRIES more
times. After that window, exits propagate unchanged.

This module is intentionally dependency-free (only stdlib) so it can
run before any Qt or PySide6 import.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


# How long after spawning the child to treat a fatal-signal exit as a
# retryable early-startup crash (vs. a real bug post-startup the user
# would want to see, like a segfault during gameplay).
EARLY_CRASH_WINDOW_SEC = 3.0

# Total launch attempts including the first one. 3 means: original + 2
# retries. Chosen because the empirical crash rate is ~25%, so
# P(all three fail) = 0.25**3 ≈ 1.5%.
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
    signal within EARLY_CRASH_WINDOW_SEC seconds, the supervisor
    relaunches it (up to MAX_LAUNCH_ATTEMPTS total). When the child
    finally exits, the supervisor exits with the same returncode and
    this function never returns.

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
    """Spawn the venv python repeatedly, retrying on early fatal-signal
    exits. Returns the final returncode (to be passed to sys.exit by
    the caller). Forwards SIGINT/SIGTERM to the child."""
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
        # Retry only on fatal-signal exits during the early window.
        is_fatal_signal = last_rc in _RETRYABLE_FATAL_SIGNALS
        in_early_window = elapsed < EARLY_CRASH_WINDOW_SEC
        if is_fatal_signal and in_early_window and attempt < MAX_LAUNCH_ATTEMPTS:
            sig_name = signal.Signals(-last_rc).name
            print(
                f"[ttmt] Early-startup crash ({sig_name} after {elapsed:.1f}s); "
                f"retrying ({attempt}/{MAX_LAUNCH_ATTEMPTS - 1}).",
                file=sys.stderr,
            )
            continue
        # Any other exit (clean failure, late crash, non-retryable signal)
        # propagates immediately.
        return last_rc
    return last_rc
