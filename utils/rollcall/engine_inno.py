"""The real Roll Call engine: Setup does the work, this reads and steers it.

The window (utils/rollcall/app.py) calls ``build_engine(mode, argv)`` with
the flags Setup put on its command line (installer.iss RcRunWindow /
RcHandOverUninstall). Everything that touches the PC goes through a
``Machine`` (utils/rollcall/winplat.py on Windows), so the run logic here is
plain Python and Qt timers and is tested on Linux with a fake machine.

Install: run Setup again with /VERYSILENT and the player's choices, follow
its progress file (utils/rollcall/protocol.py), then run the installed app's
--apply-installer-config as the player ("Saving your choices").
Update: tell the app to quit (the ready file), wait for it, run Setup
silently in the existing install's mode, reopen the app, finish once its
window is on screen.
Uninstall: run the uninstaller silently, sweep its shortcuts, remove the
user data when asked.
"""
from __future__ import annotations

import argparse
import ntpath
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QTimer

from utils.rollcall import protocol as P
from utils.rollcall.engine import (
    INDETERMINATE, INSTALL_STEPS, REMOVE_STEPS, UPDATE_STEPS, Engine, Failure,
    Flavor, InstallOptions, Installed,
)

EXIT_NO_WINDOW = P.EXIT_NO_WINDOW

TICK_MS = 100
APP_QUIT_WAIT_S = 20.0        # update: the app quits on its own after the handoff
APP_ASK_WAIT_S = 15.0         # a quit request, answered
APP_RM_WAIT_S = 40.0          # the Restart Manager's close, end to end
SETUP_CANCEL_GRACE_S = 120.0  # a stop asked for, until Setup has rolled back
CONFIG_WAIT_S = 90.0
REOPEN_WAIT_S = 120.0         # the app's window after an update (a UAC prompt may be up)
UNINSTALLER_FREE_WAIT_S = 15.0
STEP_DWELL_S = 0.35           # uninstall steps 3 and 4 are quick: let each be seen

INSTALL_STEP_UNPACK, INSTALL_STEP_COPY, INSTALL_STEP_SHORTCUTS, INSTALL_STEP_SAVE = range(4)


# ── The PC ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InstallRecord:
    """An existing install as Inno recorded it."""

    version: str
    build: int
    directory: str
    all_users: bool
    uninstaller: str = ""
    selected_tasks: tuple = ()
    deselected_tasks: tuple = ()


class Machine:
    """The calls the engine makes. Pure-Python parts live here; the Windows
    ones in winplat.WindowsMachine."""

    # Registry and settings
    def read_install(self, app_id: str, app_name: str) -> InstallRecord | None:
        raise NotImplementedError

    def delete_empty_app_key(self, app_name: str, all_users: bool) -> None:
        """Software\\flossbud\\<app name>, once the uninstaller emptied it."""

    def config_dir(self, config_dir_name: str) -> str:
        """Where the app keeps its settings: utils/build_flavor.config_dir."""
        override = os.environ.get("TTMT_CONFIG_DIR")
        if override:
            return override
        home = os.environ.get("XDG_CONFIG_HOME")
        if home:
            return os.path.join(home, config_dir_name)
        return os.path.join(os.path.expanduser("~"), ".config", config_dir_name)

    def read_settings(self, config_dir: str) -> dict:
        import json
        try:
            with open(os.path.join(config_dir, "settings.json"), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def user_programs_dir(self) -> str:
        base = os.environ.get("LOCALAPPDATA") or ntpath.join(
            os.path.expanduser("~"), "AppData", "Local")
        return ntpath.join(base, "Programs")

    def shortcut_paths(self, app_name: str, all_users: bool) -> list:
        """The .lnk files an install makes, and the Start Menu folder last."""
        return []

    def temp_dir(self) -> str:
        return tempfile.gettempdir()

    # Files
    def needs_admin(self, directory: str) -> bool:
        """True when this process cannot create ``directory`` and write in it."""
        probe = directory
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not probe or not os.path.isdir(probe):
            return True
        try:
            scratch = tempfile.mkdtemp(prefix=".ttmt-write-test-", dir=probe)
        except OSError:
            return True
        try:
            with open(os.path.join(scratch, "probe"), "w", encoding="utf-8") as fh:
                fh.write("x")
            return False
        except OSError:
            return True
        finally:
            import shutil
            shutil.rmtree(scratch, ignore_errors=True)

    def count_files(self, directory: str) -> int:
        total = 0
        for _root, _dirs, files in os.walk(directory):
            total += len(files)
        return total

    def remove_tree(self, path: str) -> bool:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.exists(path)

    def remove_dir_if_empty(self, path: str) -> None:
        try:
            os.rmdir(path)
        except OSError:
            pass

    def remove_file(self, path: str) -> None:
        P.remove(path)

    def file_free(self, path: str) -> bool:
        """False while a running program holds ``path`` (its own exe)."""
        return True

    # Processes and windows
    def is_elevated(self) -> bool:
        return False

    def app_pids(self, exe_path: str) -> list:
        raise NotImplementedError

    def pid_alive(self, pid: int) -> bool:
        raise NotImplementedError

    def has_visible_window(self, pids) -> bool:
        raise NotImplementedError

    def ask_quit(self, server_name: str) -> bool:
        """Ask a running copy to quit through its single-copy messenger. True
        once it said it will (versions older than the quit request answer
        nothing)."""
        return False

    def restart_manager_close(self, paths) -> bool:
        """Blocking. Ask Windows to close the programs using ``paths``."""
        return False

    def start(self, exe: str, args, cwd: str = ""):
        """Start a program; returns an object with poll() -> int | None."""
        raise NotImplementedError

    def launch_app(self, exe: str, args=()) -> bool:
        """Start the app detached from this process. False if it did not start."""
        raise NotImplementedError

    def delete_self_later(self, directory: str, log_path: str = "") -> str:
        """The uninstall window runs from a temp copy: remove it after exit.
        Returns what was done, for the log ("" for nothing)."""
        return ""


def server_name(config_dir: str, user: str) -> str:
    """The app's single-copy messenger (utils/instance_guard.server_name on
    Windows): kept in step by tests/test_rollcall_engine_inno.py."""
    import hashlib
    resolved = os.path.normcase(os.path.realpath(config_dir))
    key = hashlib.sha256(f"{user}\0{resolved}".encode("utf-8"))
    return f"ttmt-{key.hexdigest()[:24]}"


def current_user() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "user"


# ── Failure copy ───────────────────────────────────────────────────────────

_STEP_VERB = {
    0: "start the install",
    1: "copy the files",
    2: "create the shortcuts",
    3: "save your choices",
}

_CAUSES = {
    5: "Windows blocked writing to the install folder.",
    32: "A file in the install folder is in use by another program.",
    33: "A file in the install folder is in use by another program.",
    39: "The drive is full.",
    112: "The drive is full.",
    225: "Windows Security blocked one of the files.",
    1224: "A file in the install folder is in use by another program.",
}

_CODE_RE = re.compile(r"code (\d+)\.\s*$", re.IGNORECASE)


def hresult(code: int) -> str:
    return f"0x{(0x80070000 | (code & 0xFFFF)):08X}"


def read_setup_error(log_text: str) -> tuple:
    """(win32 code or 0, message) of the error that stopped a Setup run, from
    its /LOG file: the text of the suppressed message box Inno answered with
    Abort, or of a fatal exception."""
    lines = log_text.splitlines()
    strong: list = []      # the box Inno answered with Abort, or a fatal exception
    weak: list = []        # any other suppressed box (an exception message)
    for index, line in enumerate(lines):
        if "Defaulting to Abort for suppressed message box" in line or \
                "Fatal exception during installation process" in line:
            target = strong
        elif "Defaulting to OK for suppressed message box" in line:
            target = weak
        else:
            continue
        found = []
        for follow in lines[index + 1:]:
            if follow[:1].isdigit():     # the next timestamped entry
                break
            if follow.strip():
                found.append(follow.strip())
        if found:
            target[:] = found
    block = strong or weak
    if not block:
        return 0, ""
    code = 0
    message = ""
    for i, text in enumerate(block):
        match = _CODE_RE.search(text)
        if match:
            code = int(match.group(1))
            message = block[i + 1] if i + 1 < len(block) else ""
    if not message:
        message = block[-1]
    return code, message.rstrip(".")


def install_failure(step: int, state: P.RunState, code: int, message: str, *,
                    upgrade: bool, log_path: str, short_name: str) -> Failure:
    """README pattern: "Couldn't <step>." + one plain sentence on the cause +
    what state the PC is in."""
    step = max(0, min(3, step))
    if state.has_error("backup"):
        cause = f"Something is using the {short_name} folder (a File Explorer or command window, maybe)."
    elif state.has_error("test-failure"):
        cause = "The test run asked for this failure."
    else:
        cause = _CAUSES.get(code, "Setup stopped with an error.")
    intact = previous_intact(state, upgrade)
    if not upgrade:
        where = "Anything already copied was removed."
    elif intact:
        where = ("Nothing was changed." if state.backup != "ok"
                 else "Your previous version is back. Nothing was lost.")
    else:
        where = f"Run the installer again to repair {short_name}."
    detail = message
    if code:
        detail = f"{message} · {hresult(code)}" if message else hresult(code)
    return Failure(step=step, headline=f"Couldn’t {_STEP_VERB[step]}.",
                   body=f"{cause} {where}", detail=detail, log_path=log_path,
                   previous_intact=intact)


def previous_intact(state: P.RunState, upgrade: bool) -> bool:
    """Whether the version that was installed before a failed run still is."""
    if not upgrade:
        return True
    if state.backup == "ok":
        return state.restored
    if state.backup == "none":
        # Setup found nothing of ours in the folder: nothing was moved.
        return True
    # Stopped before the move (or never started).
    return not state.installed and state.step < INSTALL_STEP_COPY


# ── The engine ─────────────────────────────────────────────────────────────

class InnoEngine(Engine):
    """See the module docstring. ``machine`` is the PC."""

    def __init__(self, *, machine: Machine, mode: str, flavor: Flavor, setup_path: str = "",
                 ready_file: str = "", app_pid: int = 0, from_version: str = "",
                 uninstaller: str = "", app_dir: str = "", self_dir: str = "",
                 log_path: str = "", test_fail_at: int = -1, test_cancel_at: int = -1,
                 parent=None):
        super().__init__(parent)
        self._m = machine
        self._mode = mode
        self._flavor = flavor
        self._setup = setup_path
        self._ready = ready_file
        self._app_pid = app_pid
        self._from = from_version
        self._uninstaller_arg = uninstaller
        self._app_dir_arg = app_dir
        self._self_dir = self_dir
        self._log_path = log_path
        self._test_fail_at = test_fail_at       # CI: Setup fails the copy at this permille
        self._test_cancel_at = test_cancel_at   # CI: stop the install at this permille
        self._record: InstallRecord | None = None
        self._record_read = False
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._phase = ""            # what _tick is following
        self._started = 0.0
        self._phase_started = 0.0
        self._proc = None
        self._reader: P.LineReader | None = None
        self._state = P.RunState()
        self._run_dir = ""
        self._progress = ""
        self._setup_log = ""
        self._options: InstallOptions | None = None
        self._upgrade = False
        self._cancel_asked = False
        self._paused = False
        self._resume_step = 0       # Try again restarts here (the failed step)
        self._last_failure: Failure | None = None
        self._failed_options: InstallOptions | None = None
        self._closing = None        # close_app / update step 0 helper
        self._files_total = 0
        self._wipe = False
        self._reopen_launched = False
        self._step_sent = (-1, -2.0)
        self._wrote_ready = False
        self.log(f"engine inno {mode}: {flavor.app_name} {flavor.version} build {flavor.build}"
                 f" ({flavor.channel}) setup={setup_path or '-'}")
        if mode != "update":
            # The window shows before the event loop runs: by the first turn
            # of the loop it is on screen. Setup reads this to tell a window
            # that came up and then crashed from one that never started.
            QTimer.singleShot(0, lambda: self._write_ready(P.READY_UP))
        if self_dir:
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._delete_temp_copy)

    # ── Log ────────────────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        line = f"[RollCall] {message}"
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001 (no console in the frozen build)
            pass
        try:
            with open(self._log_file(), "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except OSError:
            pass

    def _log_file(self) -> str:
        return self._log_path or os.path.join(tempfile.gettempdir(), "ttmt-rollcall.log")

    def _delete_temp_copy(self) -> None:
        said = self._m.delete_self_later(self._self_dir, self._log_file())
        if said:
            self.log(f"temp copy: {said}")

    def _write_ready(self, word: str) -> None:
        if self._ready and not self._wrote_ready:
            self._wrote_ready = P.write_ready(self._ready, word)
            self.log(f"ready file {self._ready}: {word}")

    # ── What is there ──────────────────────────────────────────────────────

    def flavor(self) -> Flavor:
        return self._flavor

    def _install_record(self, refresh: bool = False) -> InstallRecord | None:
        if refresh or not self._record_read:
            self._record = self._m.read_install(self._flavor.app_id, self._flavor.app_name)
            self._record_read = True
        return self._record

    def installed(self) -> Installed | None:
        record = self._install_record(refresh=True)
        if record is None:
            return None
        return Installed(record.version, record.build, record.directory, record.all_users)

    def _config_dir(self) -> str:
        return self._m.config_dir(self._flavor.config_dir_name)

    def default_options(self) -> InstallOptions:
        record = self._install_record()
        settings = self._m.read_settings(self._config_dir())
        check = settings.get("check_for_updates_at_startup", True)
        keep_alive = bool(settings.get("keep_alive_enabled")
                          and settings.get("keep_alive_consent_acknowledged"))
        if record is not None:
            return InstallOptions(
                directory=record.directory,
                desktop_shortcut="desktopicon" in record.selected_tasks,
                # Installs older than the switch always had the entry.
                start_menu=("startmenuicon" in record.selected_tasks
                            or "startmenuicon" not in record.deselected_tasks),
                check_updates=bool(check),
                keep_alive=keep_alive)
        return InstallOptions(
            directory=ntpath.join(self._m.user_programs_dir(), self._flavor.app_name),
            check_updates=bool(check), keep_alive=keep_alive)

    def config_dir_display(self) -> str:
        if os.environ.get("TTMT_CONFIG_DIR") or os.environ.get("XDG_CONFIG_HOME"):
            return self._config_dir()
        return "%USERPROFILE%\\.config\\" + self._flavor.config_dir_name

    def previous_version(self) -> str:
        if self._from:
            return self._from
        record = self._install_record()
        return record.version if (record and self._mode == "update") else ""

    def _app_dir(self) -> str:
        if self._app_dir_arg:
            return self._app_dir_arg
        record = self._install_record()
        return record.directory if record else ""

    def _app_exe(self) -> str:
        directory = self._app_dir()
        return ntpath.join(directory, P.APP_EXE) if directory else ""

    def app_running(self) -> bool:
        exe = self._app_exe()
        return bool(exe and self._m.app_pids(exe))

    # ── Closing the running app ────────────────────────────────────────────

    def close_app(self) -> None:
        exe = self._app_exe()
        if not exe or not self._m.app_pids(exe):
            QTimer.singleShot(0, lambda: self.app_closed.emit(True))
            return
        self._closing = _Closer(self, exe)
        self._closing.done.connect_to(self._on_closer_done)
        self._ensure_timer()

    def _on_closer_done(self, closed: bool) -> None:
        self._closing = None
        self.log(f"close app: {'closed' if closed else 'still running'}")
        self.app_closed.emit(closed)

    # ── Runs ───────────────────────────────────────────────────────────────

    def _ensure_timer(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _new_run_dir(self, kind: str) -> None:
        self._run_dir = tempfile.mkdtemp(prefix=f"ttmt-{kind}-", dir=self._m.temp_dir())
        self._progress = os.path.join(self._run_dir, "progress.txt")
        self._setup_log = os.path.join(self._run_dir, "setup.log")
        self._reader = P.LineReader(self._progress)
        self._state = P.RunState()

    def _emit(self, step: int, fraction: float) -> None:
        if (step, fraction) == self._step_sent:
            return
        self._step_sent = (step, fraction)
        self.step_progress.emit(step, fraction)

    def _set_phase(self, phase: str) -> None:
        self._phase = phase
        self._phase_started = time.monotonic()

    def _fail(self, failure: Failure) -> None:
        self._timer.stop()
        self._set_phase("")
        self._last_failure = failure
        self.log(f"failed at step {failure.step}: {failure.headline} {failure.body}"
                 f" [{failure.detail}] intact={failure.previous_intact} log={failure.log_path}")
        self.failed.emit(failure)

    def _finish(self) -> None:
        self._timer.stop()
        self._set_phase("")
        self._last_failure = None
        self._resume_step = 0
        self._record_read = False
        self._drop_run_dir()
        self.log(f"{self._mode} finished")
        self.finished.emit()

    def _cancelled(self) -> None:
        self._timer.stop()
        self._set_phase("")
        self._resume_step = 0
        self._record_read = False
        self._drop_run_dir()
        self.log("cancelled; the PC is as it was")
        self.cancelled.emit()

    def _drop_run_dir(self) -> None:
        # Progress, flags and Setup's log of a run that ended well or was
        # undone. A failed run keeps them: Copy details points at the log.
        if self._run_dir:
            self._m.remove_tree(self._run_dir)
        self._run_dir = ""
        self._progress = ""

    def _start_setup(self, args) -> bool:
        self.log("setup: " + P.command_line(self._setup, args))
        try:
            self._proc = self._m.start(self._setup, args)
        except OSError as error:
            self.log(f"setup did not start: {error}")
            self._proc = None
            return False
        return True

    def _tasks(self, options: InstallOptions, settings: dict) -> str:
        tasks = []
        if options.start_menu:
            tasks.append("startmenuicon")
        if options.desktop_shortcut:
            tasks.append("desktopicon")
        if options.check_updates:
            tasks.append("checkupdates")
        if options.keep_alive:
            tasks.append("keepalive")
        return ",".join(tasks)

    # Install ----------------------------------------------------------------

    def install(self, options: InstallOptions) -> None:
        self._options = options
        self._cancel_asked = False
        self._paused = False
        record = self._install_record(refresh=True)
        self._upgrade = record is not None
        if (self._last_failure is not None and self._last_failure.step == INSTALL_STEP_SAVE
                and self._failed_options == options):
            # Setup's part is done; only "Saving your choices" failed.
            self._last_failure = None
            self._start_config()
            return
        self._resume_step = self._last_failure.step if self._last_failure else 0
        self._last_failure = None
        self._failed_options = options
        if record is not None:
            all_users = record.all_users
            directory = record.directory
        else:
            directory = options.directory
            all_users = self._m.needs_admin(directory)
        settings = self._m.read_settings(self._config_dir())
        self._new_run_dir("setup")
        args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                "/ALLUSERS" if all_users else "/CURRENTUSER",
                f"/DIR={directory}", f"/TASKS={self._tasks(options, settings)}",
                f"/LOG={self._setup_log}", f"/RCPROGRESS={self._progress}"]
        if self._test_fail_at >= 0:
            args.append(f"/RCTESTFAIL={self._test_fail_at}")
        self._started = time.monotonic()
        self._emit_install(INSTALL_STEP_UNPACK, INDETERMINATE)
        if not self._start_setup(args):
            self._fail(Failure(
                step=0, headline="Couldn’t start the install.",
                body="Windows didn't start Setup. Nothing was installed." if not self._upgrade
                else "Windows didn't start Setup. Nothing was changed.",
                detail=self._setup, log_path=self._log_path))
            return
        self._set_phase("setup")
        self._ensure_timer()

    def _emit_install(self, step: int, fraction: float) -> None:
        # Try again restarts the failed step: steps before it stay done.
        if step < self._resume_step:
            step, fraction = self._resume_step, INDETERMINATE
        self._emit(step, fraction)

    def can_cancel(self) -> bool:
        if self._mode != "install" or self._upgrade or self._cancel_asked:
            return False
        if self._phase != "setup":
            return False
        return not self._state.installed and self._state.step < INSTALL_STEP_SHORTCUTS

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if not self._progress:
            return
        if paused:
            P.touch(self._progress + P.PAUSE_SUFFIX)
        else:
            P.remove(self._progress + P.PAUSE_SUFFIX)

    def cancel(self) -> None:
        self.log("cancel asked")
        self._cancel_asked = True
        if self._progress:
            P.touch(self._progress + P.CANCEL_SUFFIX)
            P.remove(self._progress + P.PAUSE_SUFFIX)
        if self._phase == "":
            QTimer.singleShot(0, self._cancelled)

    def _follow_setup(self) -> None:
        for line in self._reader.read() if self._reader else []:
            self._state.apply(line)
        s = self._state
        if (self._test_cancel_at >= 0 and not self._cancel_asked and s.step == INSTALL_STEP_COPY
                and s.permille >= self._test_cancel_at and self.can_cancel()):
            self.log(f"test: stopping the install at {s.permille}")
            self.cancel()
        if self._mode == "install":
            if s.step >= INSTALL_STEP_SHORTCUTS or s.installed:
                self._emit_install(INSTALL_STEP_SHORTCUTS, INDETERMINATE)
            elif s.step == INSTALL_STEP_COPY:
                self._emit_install(INSTALL_STEP_COPY, s.permille / 1000.0)
            else:
                self._emit_install(INSTALL_STEP_UNPACK, INDETERMINATE)
        code = self._proc.poll() if self._proc is not None else 0
        if code is None:
            if (self._cancel_asked and
                    time.monotonic() - self._phase_started > SETUP_CANCEL_GRACE_S):
                self.log("setup did not stop in time")
            return
        for line in self._reader.read() if self._reader else []:
            self._state.apply(line)
        self.log(f"setup exited with {code}; {self._summary()}")
        if self._mode == "install":
            self._install_setup_exited(code)
        else:
            self._update_setup_exited(code)

    def _summary(self) -> str:
        s = self._state
        return (f"hello={s.hello} step={s.step} backup={s.backup or '-'} cancelled={s.cancelled}"
                f" restored={s.restored} installed={s.installed} errors={s.errors}")

    def _read_log(self) -> str:
        try:
            with open(self._setup_log, "r", encoding="utf-8-sig", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def _install_setup_exited(self, code: int) -> None:
        s = self._state
        if code == P.SETUP_OK and s.installed:
            if self._cancel_asked:
                if self._upgrade:
                    # Not offered on an upgrade (can_cancel); a stop that
                    # arrived anyway is too late: report what is true.
                    self._start_config()
                    return
                self._start_undo()
                return
            self._start_config()
            return
        if not s.hello and code == P.SETUP_CANCELLED_BEFORE_INSTALL:
            self.log("setup never started its install: the administrator prompt was declined")
            self._cancelled()
            return
        if self._cancel_asked and (s.cancelled or not s.installed):
            self._cancelled()
            return
        error_code, message = read_setup_error(self._read_log())
        failed_step = max(0, s.step)
        if s.has_error("backup"):
            failed_step = INSTALL_STEP_UNPACK
        self._fail(install_failure(failed_step, s, error_code, message, upgrade=self._upgrade,
                                   log_path=self._setup_log,
                                   short_name=self._flavor.short_name))

    # Fresh install stopped after Setup had already finished: take it out.
    def _start_undo(self) -> None:
        record = self._install_record(refresh=True)
        uninstaller = record.uninstaller if record else ""
        if not uninstaller:
            uninstaller = ntpath.join(self._options.directory, "unins000.exe")
        self.log("stop arrived after Setup finished: removing the fresh install")
        try:
            self._proc = self._m.start(uninstaller, ["/VERYSILENT", "/SUPPRESSMSGBOXES",
                                                     "/NORESTART"])
        except OSError as error:
            self.log(f"could not run the uninstaller: {error}")
            self._fail(Failure(
                step=INSTALL_STEP_SHORTCUTS, headline="Couldn’t stop the install.",
                body="It finished before it could be stopped. Uninstall it from Settings > Apps.",
                log_path=self._setup_log))
            return
        self._set_phase("undo")

    def _follow_undo(self) -> None:
        code = self._proc.poll()
        if code is None:
            return
        self.log(f"uninstaller (undo) exited with {code}")
        if code == 0:
            self._cancelled()
        else:
            self._fail(Failure(
                step=INSTALL_STEP_SHORTCUTS, headline="Couldn’t stop the install.",
                body="It finished before it could be stopped. Uninstall it from Settings > Apps.",
                log_path=self._setup_log))

    # "Saving your choices": the installed app merges them into settings.json.
    def _start_config(self) -> None:
        options = self._options
        record = self._install_record(refresh=True)
        directory = record.directory if record else options.directory
        settings = self._m.read_settings(self._config_dir())
        already = bool(settings.get("keep_alive_enabled")
                       and settings.get("keep_alive_consent_acknowledged"))
        # An existing consent is never rewritten (installer_merge never strips one).
        keep_alive = options.keep_alive and not already
        args = ["--apply-installer-config",
                f"--check-updates={1 if options.check_updates else 0}",
                f"--keep-alive={1 if keep_alive else 0}"]
        self._emit_install(INSTALL_STEP_SAVE, INDETERMINATE)
        exe = ntpath.join(directory, P.APP_EXE)
        self.log("saving choices: " + P.command_line(exe, args))
        try:
            self._proc = self._m.start(exe, args, cwd=directory)
        except OSError as error:
            self._config_failed(f"{error}")
            return
        self._set_phase("config")
        self._ensure_timer()

    def _follow_config(self) -> None:
        code = self._proc.poll()
        if code is None:
            if time.monotonic() - self._phase_started > CONFIG_WAIT_S:
                self._config_failed("timed out")
            return
        self.log(f"saving choices exited with {code}")
        if code == 0:
            self._emit_install(INSTALL_STEP_SAVE, 1.0)
            self._finish()
        else:
            self._config_failed(f"exit code {code}")

    def _config_failed(self, detail: str) -> None:
        self._fail(Failure(
            step=INSTALL_STEP_SAVE, headline="Couldn’t save your choices.",
            body=f"{self._flavor.short_name} is installed, but its settings file couldn't be "
                 "updated. You can set these in Settings.",
            detail=detail, log_path=self._log_path))

    # Update -----------------------------------------------------------------

    def update(self) -> None:
        self._cancel_asked = False
        record = self._install_record(refresh=True)
        self._upgrade = True
        self._started = time.monotonic()
        self._write_ready(P.READY_UP)       # the app quits once it reads this
        self._emit(0, INDETERMINATE)
        self._closing = None
        self._set_phase("update-wait-app")
        self.log(f"update {self.previous_version() or '?'} -> {self._flavor.version}; "
                 f"waiting for the app (pid {self._app_pid}) to quit; install "
                 f"{record.directory if record else 'not found'}")
        self._ensure_timer()

    def _app_gone(self) -> bool:
        if self._app_pid and self._m.pid_alive(self._app_pid):
            return False
        exe = self._app_exe()
        return not (exe and self._m.app_pids(exe))

    def _follow_update_wait_app(self) -> None:
        if self._app_gone():
            self._closing = None
            self._emit(0, 1.0)
            self._start_update_setup()
            return
        waited = time.monotonic() - self._phase_started
        if waited > APP_QUIT_WAIT_S and self._closing is None:
            self.log("the app has not quit on its own: asking it")
            self._closing = _Closer(self, self._app_exe())
            self._closing.done.connect_to(self._on_update_closer_done)

    def _on_update_closer_done(self, closed: bool) -> None:
        if self._phase != "update-wait-app":
            return
        if closed or self._app_gone():
            self._closing = None
            self._emit(0, 1.0)
            self._start_update_setup()
            return
        self._fail(Failure(
            step=0, headline="The update didn’t finish.",
            body=f"{self._flavor.short_name} didn't close, so nothing was changed.",
            log_path=self._log_path, previous_intact=True))

    def _start_update_setup(self) -> None:
        record = self._install_record(refresh=True)
        self._new_run_dir("update")
        args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        if record is not None:
            args += ["/ALLUSERS" if record.all_users else "/CURRENTUSER",
                     f"/DIR={record.directory}"]
        else:
            args.append("/CURRENTUSER")
        args += [f"/LOG={self._setup_log}", f"/RCPROGRESS={self._progress}"]
        if self._test_fail_at >= 0:
            args.append(f"/RCTESTFAIL={self._test_fail_at}")
        self._emit(1, 0.0)
        if not self._start_setup(args):
            self._fail(Failure(
                step=1, headline="The update didn’t finish.",
                body="Windows didn't start Setup, so nothing was changed.",
                detail=self._setup, log_path=self._log_path, previous_intact=True))
            return
        self._set_phase("update-setup")

    def _follow_update_setup(self) -> None:
        s = self._state
        if s.installed or s.step >= INSTALL_STEP_SHORTCUTS:
            fraction = 0.97
        elif s.step == INSTALL_STEP_COPY:
            fraction = 0.05 + 0.9 * s.permille / 1000.0
        else:
            fraction = 0.02
        self._emit(1, fraction)
        self._follow_setup()

    def _update_setup_exited(self, code: int) -> None:
        s = self._state
        if code == P.SETUP_OK and s.installed:
            self._emit(1, 1.0)
            self._start_reopen()
            return
        if not s.hello and code == P.SETUP_CANCELLED_BEFORE_INSTALL:
            self._fail(Failure(
                step=1, headline="The update didn’t finish.",
                body="Windows asked for permission and it wasn't given, so nothing was changed.",
                log_path=self._setup_log, previous_intact=True))
            return
        error_code, message = read_setup_error(self._read_log())
        intact = previous_intact(s, True)
        if intact:
            body = ("Your previous version is back. Nothing was lost." if s.backup == "ok"
                    else "Nothing was changed.")
        else:
            body = f"Run the installer again to repair {self._flavor.short_name}."
        detail = message
        if error_code:
            detail = f"{message} · {hresult(error_code)}" if message else hresult(error_code)
        self._fail(Failure(step=1, headline="The update didn’t finish.", body=body,
                           detail=detail, log_path=self._setup_log, previous_intact=intact))

    def _start_reopen(self) -> None:
        self._emit(2, INDETERMINATE)
        self._reopen_launched = self.open_app()
        self._set_phase("update-reopen")

    def _follow_update_reopen(self) -> None:
        exe = self._app_exe()
        pids = self._m.app_pids(exe) if exe else []
        if pids and self._m.has_visible_window(pids):
            self._emit(2, 1.0)
            self._finish()
            return
        waited = time.monotonic() - self._phase_started
        if waited < REOPEN_WAIT_S and (pids or waited < 15.0):
            return
        if pids:
            # Running, but no window yet (an administrator prompt, perhaps):
            # the update is done either way.
            self.log("the app is running but its window is not up yet: done anyway")
            self._finish()
            return
        self._fail(Failure(
            step=2, headline=f"Couldn’t reopen {self._flavor.short_name}.",
            body=f"The update is installed. Open {self._flavor.short_name} from the Start Menu.",
            log_path=self._log_path, previous_intact=False))

    # Uninstall --------------------------------------------------------------

    def uninstall(self, remove_user_data: bool) -> None:
        self._wipe = bool(remove_user_data)
        self._cancel_asked = False
        # Read now: the uninstaller deletes the record, and the sweep after it
        # needs the install's mode (per-user or all-users shortcuts and keys).
        self._install_record(refresh=True)
        self._started = time.monotonic()
        self._emit(0, INDETERMINATE)
        self._set_phase("remove-close")
        if self.app_running():
            self._closing = _Closer(self, self._app_exe())
            self._closing.done.connect_to(self._on_remove_closer_done)
        self._ensure_timer()

    def _on_remove_closer_done(self, closed: bool) -> None:
        self._closing = None
        if not closed:
            self._fail(Failure(
                step=0, headline="Couldn’t close the app.",
                body=f"{self._flavor.short_name} is still running, so nothing was removed.",
                log_path=self._log_path))

    def _uninstaller(self) -> str:
        if self._uninstaller_arg:
            return self._uninstaller_arg
        record = self._install_record()
        if record and record.uninstaller:
            return record.uninstaller
        return ntpath.join(self._app_dir(), "unins000.exe")

    def _follow_remove_close(self) -> None:
        if self._closing is not None:
            return
        uninstaller = self._uninstaller()
        # The uninstaller that handed over to this window may still be
        # exiting: the silent one cannot delete a running unins000.exe.
        waited = time.monotonic() - self._phase_started
        if not self._m.file_free(uninstaller) and waited < UNINSTALLER_FREE_WAIT_S:
            return
        self._emit(0, 1.0)
        self._new_run_dir("uninstall")
        directory = self._app_dir()
        self._files_total = max(1, self._m.count_files(directory)) if directory else 1
        args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                f"/LOG={self._setup_log}", f"/RCPROGRESS={self._progress}"]
        self.log("uninstaller: " + P.command_line(uninstaller, args))
        try:
            self._proc = self._m.start(uninstaller, args)
        except OSError as error:
            self._fail(Failure(
                step=1, headline="Couldn’t remove the files.",
                body=f"Windows didn't start the uninstaller. {self._flavor.short_name} is still installed.",
                detail=f"{error}", log_path=self._log_path))
            return
        self._emit(1, 0.0)
        self._set_phase("remove-files")

    def _follow_remove_files(self) -> None:
        for line in self._reader.read() if self._reader else []:
            self._state.apply(line)
        directory = self._app_dir()
        if directory:
            left = self._m.count_files(directory)
            self._emit(1, min(0.98, max(0.0, 1.0 - left / self._files_total)))
        code = self._proc.poll()
        if code is None:
            return
        for line in self._reader.read() if self._reader else []:
            self._state.apply(line)
        self.log(f"uninstaller exited with {code}; {self._summary()}")
        if code != 0:
            declined = not self._state.hello
            error_code, message = read_setup_error(self._read_log())
            self._fail(Failure(
                step=1, headline="Couldn’t remove the files.",
                body=("Windows asked for permission and it wasn't given. "
                      if declined else "The uninstaller stopped with an error. ")
                + f"{self._flavor.short_name} is still installed.",
                detail=(f"{message} · {hresult(error_code)}" if error_code else message),
                log_path=self._setup_log))
            return
        self._emit(1, 1.0)
        self._emit(2, 0.0)
        self._set_phase("remove-shortcuts")

    def _follow_remove_shortcuts(self) -> None:
        # A short dwell per step so each toon visibly leaves.
        if time.monotonic() - self._phase_started < STEP_DWELL_S:
            return
        record = self._install_record()
        all_users = record.all_users if record else False
        for path in self._m.shortcut_paths(self._flavor.app_name, all_users):
            if path.lower().endswith(".lnk"):
                self._m.remove_file(path)
            else:
                self._m.remove_dir_if_empty(path)
        self._emit(2, 1.0)
        self._emit(3, 0.0)
        self._set_phase("remove-cleanup")

    def _follow_remove_cleanup(self) -> None:
        if time.monotonic() - self._phase_started < STEP_DWELL_S:
            return
        record = self._install_record()
        all_users = record.all_users if record else False
        directory = self._app_dir()
        if directory:
            for leftover in (directory + P.BACKUP_SUFFIX, directory + P.TRASH_SUFFIX):
                self._m.remove_tree(leftover)
            self._m.remove_dir_if_empty(directory)
        self._m.delete_empty_app_key(self._flavor.app_name, all_users)
        if self._wipe:
            config = self._config_dir()
            self.log(f"removing the user data in {config}")
            if os.path.isdir(config) and not self._m.remove_tree(config):
                self._fail(Failure(
                    step=3, headline="Couldn’t clean up.",
                    body=f"{self._flavor.short_name} is removed, but some of your settings "
                         "couldn't be deleted.",
                    detail=config, log_path=self._setup_log))
                return
        self._emit(3, 1.0)
        self._record_read = False
        self._finish()

    # Open ---------------------------------------------------------------------

    def open_app(self) -> bool:
        exe = ntpath.join(self._app_dir_now(), P.APP_EXE)
        ok = self._m.launch_app(exe)
        self.log(f"open {exe}: {'started' if ok else 'did not start'}")
        return ok

    def _app_dir_now(self) -> str:
        record = self._install_record(refresh=True)
        if record is not None:
            return record.directory
        if self._options is not None:
            return self._options.directory
        return self._app_dir()

    def open_uninstaller(self) -> bool:
        record = self._install_record(refresh=True)
        if record is None or not record.uninstaller:
            return False
        try:
            self._m.start(record.uninstaller, [])
        except OSError as error:
            self.log(f"could not open the uninstaller: {error}")
            return False
        return True

    # ── The clock ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        try:
            if self._closing is not None:
                self._closing.tick()
            phase = self._phase
            if phase == "setup":
                self._follow_setup()
            elif phase == "undo":
                self._follow_undo()
            elif phase == "config":
                self._follow_config()
            elif phase == "update-wait-app":
                self._follow_update_wait_app()
            elif phase == "update-setup":
                self._follow_update_setup()
            elif phase == "update-reopen":
                self._follow_update_reopen()
            elif phase == "remove-close":
                self._follow_remove_close()
            elif phase == "remove-files":
                self._follow_remove_files()
            elif phase == "remove-shortcuts":
                self._follow_remove_shortcuts()
            elif phase == "remove-cleanup":
                self._follow_remove_cleanup()
            elif self._closing is None:
                self._timer.stop()
        except Exception as error:  # noqa: BLE001 (a bug must not freeze the window)
            import traceback
            self.log(f"engine error: {error}\n{traceback.format_exc()}")
            self._fail(Failure(
                step=max(0, self._step_sent[0]), headline="Something went wrong.",
                body="The installer hit an unexpected error.", detail=str(error),
                log_path=self._log_path,
                previous_intact=previous_intact(self._state, self._upgrade)))


class _Signal:
    """A one-shot callback (the closer lives inside the engine's tick)."""

    def __init__(self):
        self._slot = None

    def connect_to(self, slot) -> None:
        self._slot = slot

    def emit(self, value) -> None:
        if self._slot is not None:
            self._slot(value)


class _Closer:
    """Closes the running app politely, driven by the engine's tick: the quit
    request (versions with the single-copy messenger), then the Restart
    Manager (any version), never a kill."""

    def __init__(self, engine: InnoEngine, exe: str):
        self.engine = engine
        self.exe = exe
        self.done = _Signal()
        self._m = engine._m
        self._started = time.monotonic()
        self._stage = "ask"
        self._rm_thread: threading.Thread | None = None
        self._rm_result: list = []
        self._finished = False

    def _running(self) -> bool:
        return bool(self.exe and self._m.app_pids(self.exe))

    def tick(self) -> None:
        if self._finished:
            return
        if not self._running():
            self._end(True)
            return
        elapsed = time.monotonic() - self._started
        if self._stage == "ask":
            name = server_name(self._m.config_dir(self.engine._flavor.config_dir_name),
                               current_user())
            answered = self._m.ask_quit(name)
            self.engine.log(f"quit request to {name}: {'accepted' if answered else 'no answer'}")
            self._stage = "wait-ask" if answered else "rm"
            self._started = time.monotonic()
        elif self._stage == "wait-ask":
            if elapsed > APP_ASK_WAIT_S:
                self._stage = "rm"
        elif self._stage == "rm":
            self.engine.log("closing the app with the Restart Manager")
            self._rm_thread = threading.Thread(
                target=lambda: self._rm_result.append(self._m.restart_manager_close([self.exe])),
                daemon=True)
            self._rm_thread.start()
            self._stage = "wait-rm"
            self._started = time.monotonic()
        elif self._stage == "wait-rm":
            if elapsed > APP_RM_WAIT_S:
                self._end(False)

    def _end(self, closed: bool) -> None:
        self._finished = True
        self.done.emit(closed)


# ── Building it from Setup's flags ─────────────────────────────────────────

def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rollcall-engine", add_help=False)
    parser.add_argument("--setup", default="")
    parser.add_argument("--log", default="")
    parser.add_argument("--ready-file", default="")
    parser.add_argument("--app-name", default="ToonTown MultiTool")
    parser.add_argument("--app-version", default="vDEV")
    parser.add_argument("--build", type=int, default=0)
    parser.add_argument("--app-id", default="")
    parser.add_argument("--config-dir-name", default="toontown_multitool")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--payload-bytes", type=int, default=0)
    parser.add_argument("--app-pid", type=int, default=0)
    parser.add_argument("--from-version", default="")
    parser.add_argument("--uninstaller", default="")
    parser.add_argument("--app-dir", default="")
    parser.add_argument("--self-dir", default="")
    parser.add_argument("--test-fail-at", type=int, default=-1)
    parser.add_argument("--test-cancel-at", type=int, default=-1)
    args, unknown = parser.parse_known_args(list(argv))
    args.unknown = unknown
    return args


def build_engine(mode: str, argv, *, machine: Machine | None = None) -> Engine:
    args = parse_args(argv)
    flavor = Flavor(app_name=args.app_name, version=args.app_version, build=args.build,
                    app_id=args.app_id, config_dir_name=args.config_dir_name,
                    channel=args.channel, payload_bytes=max(0, args.payload_bytes))
    if machine is None:
        if sys.platform != "win32":
            raise RuntimeError("the Inno engine runs on Windows only (use --demo elsewhere)")
        from utils.rollcall.winplat import WindowsMachine
        machine = WindowsMachine()
    engine = InnoEngine(machine=machine, mode=mode, flavor=flavor, setup_path=args.setup,
                        ready_file=args.ready_file, app_pid=args.app_pid,
                        from_version=args.from_version, uninstaller=args.uninstaller,
                        app_dir=args.app_dir, self_dir=args.self_dir, log_path=args.log,
                        test_fail_at=args.test_fail_at, test_cancel_at=args.test_cancel_at)
    if args.unknown:
        engine.log(f"engine ignored unknown flags: {args.unknown}")
    return engine
