"""Detect the user's default terminal and build a command-line for it.

No standard exists for "default terminal" on Linux; probe $TERMINAL,
then a hardcoded list of common terminals. Each terminal has its own
flag convention for "run this command and exit when it does"; we
hardcode the mapping for the ~6 we support.

If detect_terminal() returns None, the caller falls back to a
copy-command dialog instead.
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import threading
from typing import Callable, List, Optional


_log = logging.getLogger(__name__)


# Detection order: gnome-terminal first because GNOME has the largest
# installed base; konsole second for KDE; XFCE, kitty, alacritty next;
# xterm last as the universal X11 fallback.
TERMINAL_ORDER = [
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "kitty",
    "alacritty",
    "xterm",
]


def detect_terminal() -> Optional[str]:
    """Return a path to a usable terminal, or None."""
    env = os.environ.get("TERMINAL")
    if env:
        found = shutil.which(env)
        if found:
            return found
    for name in TERMINAL_ORDER:
        found = shutil.which(name)
        if found:
            return found
    return None


def build_argv(terminal_path: str, cmd: List[str]) -> List[str]:
    """Return the full argv to spawn the given terminal running `cmd`."""
    name = os.path.basename(terminal_path)
    if name == "gnome-terminal":
        return [terminal_path, "--", *cmd]
    if name == "konsole":
        return [terminal_path, "-e", *cmd]
    if name == "xterm":
        return [terminal_path, "-e", *cmd]
    if name == "xfce4-terminal":
        # xfce4-terminal --command takes a single string parsed by a shell.
        # shlex.quote each element so paths containing spaces survive.
        return [terminal_path, "--command", " ".join(shlex.quote(a) for a in cmd)]
    if name == "kitty":
        return [terminal_path, *cmd]
    if name == "alacritty":
        return [terminal_path, "-e", *cmd]
    # Fallback: -e is most common.
    return [terminal_path, "-e", *cmd]


def run_in_terminal(cmd: List[str], on_exit: Callable[[int], None]) -> bool:
    """Spawn `cmd` inside the user's default terminal. Calls on_exit
    with the terminal's exit code in a background thread. Returns False
    if no terminal could be detected.
    """
    terminal = detect_terminal()
    if terminal is None:
        return False
    argv = build_argv(terminal, cmd)
    try:
        proc = subprocess.Popen(argv)
    except (OSError, subprocess.SubprocessError):
        return False

    def _wait():
        rc = proc.wait()
        try:
            on_exit(rc)
        except Exception:
            _log.exception("on_exit callback raised in terminal launcher thread")

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    return True
