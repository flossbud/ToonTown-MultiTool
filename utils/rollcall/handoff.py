"""What the running app calls to hand an update over to the update window.

Standard library only (and utils/rollcall/protocol.py): the app calls this
from "Restart & update" and at startup for "Next launch", the latter before
any QApplication exists.

The app starts the downloaded Setup in update mode with its pid and its
version. Setup unpacks the Roll Call update window and starts it; once the
window is on screen it writes "up" to the ready file, and only then does
this return True: the caller quits, and the window (already showing) waits
for this process to exit, installs, and reopens the app. If the window never
comes up, this returns False and the app keeps running; the caller can fall
back to the old silent update (/SILENT /SUPPRESSMSGBOXES /RELAUNCH=1).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

from utils.rollcall import protocol as P

READY_TIMEOUT_S = 60.0     # unpacking the window, a slow disk, a virus scan
POLL_S = 0.1

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def update_args(*, app_pid: int, from_version: str, ready_file: str) -> list:
    return ["/RCMODE=update", f"/RCPID={int(app_pid)}", f"/RCFROM={from_version}",
            f"/RCREADY={ready_file}"]


def setup_working_dir() -> str:
    """Where Setup is started: never the app's own folder.

    The app usually runs in its install folder (Inno starts shortcuts and
    [Run] entries in the exe's folder, and the update window reopens it
    there). Setup's loader keeps the folder it was started in for its whole
    life, and so does the Setup it runs until an install begins, which this
    one never does: it waits for the update window. A process's working
    folder cannot be renamed, so started from the app it would keep the
    second Setup from moving the installed version aside, and every update
    would fail. Inno moves itself to the system folder for the same reason."""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or ""
    system = os.path.join(root, "System32") if root else ""
    return system if system and os.path.isdir(system) else tempfile.gettempdir()


def _popen(command: str):
    """Setup must outlive this process: break away from a job that would
    take it down when the app exits."""
    cwd = setup_working_dir()
    if sys.platform != "win32":
        return subprocess.Popen(command, shell=True, close_fds=True, cwd=cwd)
    flags = _CREATE_NEW_PROCESS_GROUP | _CREATE_BREAKAWAY_FROM_JOB
    try:
        return subprocess.Popen(command, close_fds=True, creationflags=flags, cwd=cwd)
    except OSError as error:
        if getattr(error, "winerror", None) != 5:
            raise
        return subprocess.Popen(command, close_fds=True,
                                creationflags=_CREATE_NEW_PROCESS_GROUP, cwd=cwd)


def start_update_window(setup_path: str, *, app_pid: int, from_version: str,
                        timeout_s: float = READY_TIMEOUT_S, popen=_popen,
                        clock=time.monotonic, sleep=time.sleep, log=print) -> bool:
    """Start Setup in update mode; True once the update window is up."""
    if not setup_path or not os.path.isfile(setup_path):
        log(f"[RollCall] handoff: no installer at {setup_path!r}")
        return False
    ready = os.path.join(tempfile.gettempdir(),
                         f"ttmt-update-ready-{int(app_pid)}-{int(time.time() * 1000)}.txt")
    P.remove(ready)
    try:
        command = P.command_line(setup_path, update_args(
            app_pid=app_pid, from_version=from_version, ready_file=ready))
    except ValueError as error:
        log(f"[RollCall] handoff: {error}")
        return False
    log(f"[RollCall] handoff: {command}")
    try:
        proc = popen(command)
    except OSError as error:
        log(f"[RollCall] handoff: Setup did not start: {error}")
        return False
    deadline = clock() + timeout_s
    while True:
        word = P.read_ready(ready)
        if word == P.READY_UP:
            log("[RollCall] handoff: the update window is up")
            P.remove(ready)
            return True
        if word == P.READY_NO_WINDOW:
            log("[RollCall] handoff: Setup could not show the update window")
            P.remove(ready)
            return False
        if proc.poll() is not None and not P.read_ready(ready):
            log(f"[RollCall] handoff: Setup exited ({proc.returncode}) without a window")
            return False
        if clock() >= deadline:
            log("[RollCall] handoff: no update window in time")
            return False
        sleep(POLL_S)
