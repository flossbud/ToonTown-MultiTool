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


def _which(name: str) -> Optional[str]:
    """Resolve `name` to a full path, querying the host when sandboxed.

    Inside a Flatpak sandbox the host's terminals are not on the sandbox PATH,
    so shutil.which would always miss. Route through flatpak-spawn --host so we
    probe the host PATH instead (mirrors wine_runtimes._host_command_exists).
    """
    from utils.host_spawn import in_flatpak, host_check_output
    if in_flatpak():
        try:
            out = host_check_output(["which", name], timeout=3)
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            # `which` appends a trailing newline; strip it so build_argv's
            # os.path.basename match (e.g. the "konsole" branch) still fires.
            line = out.strip().splitlines()[0].strip() if out.strip() else ""
            return line or None
        except Exception:
            return None
    return shutil.which(name)


def detect_terminal() -> Optional[str]:
    """Return a path to a usable terminal, or None."""
    env = os.environ.get("TERMINAL")
    if env:
        found = _which(env)
        if found:
            return found
    for name in TERMINAL_ORDER:
        found = _which(name)
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
        from utils.host_spawn import in_flatpak, host_popen
        if in_flatpak():
            # The terminal is a host GUI process: launch it on the host with
            # X11 auth forwarded (the same path the game launchers use). The
            # command payload stays raw -- flatpak-spawn must not be nested,
            # and forward_xauthority is a no-op unless an env is passed.
            proc = host_popen(argv, env=os.environ.copy(), forward_xauthority=True)
        else:
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
