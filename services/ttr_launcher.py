"""
TTR Launcher Service — handles launching the actual TTREngine process
and monitoring its lifecycle (PID, exit code).
"""

from __future__ import annotations

import os
import subprocess
import threading
import tempfile
from PySide6.QtCore import QObject, Signal
from services.launcher_env import build_launcher_env
from services.ttr_login_service import ENGINE_SEARCH_PATHS, get_engine_executable_name
from utils.game_registry import GameRegistry
from utils.host_spawn import host_popen

_CUSTOM_APPROVAL_KEY = "ttr_engine_dir_approved_custom_dir"
_TRUSTED_ENGINE_DIRS = {
    os.path.realpath(path)
    for path in ENGINE_SEARCH_PATHS
}
def _build_log_tail(stderr_content: str, stdout_content: str) -> str:
    parts = []
    if stderr_content:
        parts.append("stderr:\n" + stderr_content)
    if stdout_content:
        parts.append("stdout:\n" + stdout_content)
    combined = "\n\n".join(parts).strip()
    if len(combined) > 4000:
        combined = combined[-4000:]
    return combined


def _approved_custom_engine_dir(settings_manager) -> str | None:
    if settings_manager is None:
        return None
    approved = settings_manager.get(_CUSTOM_APPROVAL_KEY, "")
    return os.path.realpath(approved) if approved else None


def _is_trusted_engine_path(engine_path: str, settings_manager=None) -> bool:
    """Return True if the engine path is explicitly trusted or user-approved."""
    real_path = os.path.realpath(engine_path)
    if not os.path.isfile(real_path):
        return False
    engine_dir = os.path.realpath(os.path.dirname(engine_path))
    if engine_dir in _TRUSTED_ENGINE_DIRS:
        return True
    approved_custom = _approved_custom_engine_dir(settings_manager)
    return bool(approved_custom and engine_dir == approved_custom)

class TTRLauncher(QObject):
    game_launched = Signal(int)     # (pid)
    game_exited = Signal(int, str)  # (return_code, raw_log_tail)
    launch_failed = Signal(str)     # (error_message)

    def __init__(self, parent=None, settings_manager=None):
        super().__init__(parent)
        self._game_process = None
        self.settings_manager = settings_manager

    def launch(self, gameserver: str, cookie: str, engine_dir: str):
        """Launch TTREngine with credentials in a background thread."""
        binary_name = get_engine_executable_name()
        engine_path = os.path.join(engine_dir, binary_name)

        if not os.path.isfile(engine_path):
            self.launch_failed.emit(f"TTREngine not found at {engine_path}")
            return

        if not _is_trusted_engine_path(engine_path, self.settings_manager):
            self.launch_failed.emit(
                "TTREngine path is not in the trusted install list. "
                "Re-select it in Settings to approve a custom install."
            )
            return

        # The official TTR Flatpak data dir may be mounted read-only inside
        # TTMT, so chmod failures are ignored. The host launch below still
        # executes the selected engine path directly.
        if not os.access(engine_path, os.X_OK):
            try:
                os.chmod(engine_path, 0o755)
            except Exception:
                pass

        env = build_launcher_env({
            "TTR_GAMESERVER": gameserver,
            "TTR_PLAYCOOKIE": cookie,
        })
        # XAUTHORITY forwarding is host_popen's job: forward_xauthority=True (below)
        # copies the sandbox cookie to a host-visible path and keeps it from being
        # stripped as a sandbox-only var. Don't also set it here - that would be a
        # redundant double copy with two sources of truth.

        def _run():
            stdout_fd = None
            stderr_fd = None
            stdout_path = None
            stderr_path = None
            stdout_fh = None
            stderr_fh = None
            retcode = None
            try:
                import sys
                stdout_fd, stdout_path = tempfile.mkstemp(
                    prefix="ttmt-ttr-stdout-", suffix=".log"
                )
                stderr_fd, stderr_path = tempfile.mkstemp(
                    prefix="ttmt-ttr-stderr-", suffix=".log"
                )
                stdout_fh = os.fdopen(stdout_fd, "w+b")
                stdout_fd = None
                stderr_fh = os.fdopen(stderr_fd, "w+b")
                stderr_fd = None
                kwargs = {}
                if sys.platform == "win32":
                    # Break out of the parent's Windows Job Object so closing
                    # multitool doesn't take running games down with it when
                    # the job has JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
                    kwargs["creationflags"] = (
                        subprocess.DETACHED_PROCESS
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_BREAKAWAY_FROM_JOB
                    )

                def _spawn():
                    return host_popen(
                        [engine_path],
                        cwd=engine_dir,
                        env=env,
                        forward_xauthority=True,
                        stdout=stdout_fh,
                        stderr=stderr_fh,
                        **kwargs
                    )

                try:
                    self._game_process = _spawn()
                except OSError as e:
                    if sys.platform != "win32" or getattr(e, "winerror", None) != 5:
                        raise
                    kwargs["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
                    self._game_process = _spawn()
                pid = self._game_process.pid
                GameRegistry.instance().register(pid, "ttr")
                self.game_launched.emit(pid)

                # Wait for game to exit
                retcode = self._game_process.wait()
                GameRegistry.instance().unregister(pid)
                self._game_process = None

                def _read_capture(fh):
                    try:
                        fh.flush()
                        fh.seek(0)
                        return fh.read().decode("utf-8", "replace").strip()
                    except Exception as e:
                        return f"<failed to read capture: {e}>"

                stdout_content = _read_capture(stdout_fh)
                stderr_content = _read_capture(stderr_fh)
                raw_log = ""
                if retcode != 0:
                    raw_log = _build_log_tail(stderr_content, stdout_content)
                self.game_exited.emit(retcode, raw_log)

            except Exception as e:
                self.launch_failed.emit(f"Launch error: {e}")
            finally:
                for fd in (stdout_fd, stderr_fd):
                    try:
                        if fd is not None:
                            os.close(fd)
                    except Exception:
                        pass
                for fh in (stdout_fh, stderr_fh):
                    try:
                        if fh:
                            fh.close()
                    except Exception:
                        pass
                if retcode == 0:
                    for path in (stdout_path, stderr_path):
                        try:
                            if path:
                                os.unlink(path)
                        except OSError:
                            pass

        threading.Thread(target=_run, daemon=True).start()

    def kill(self):
        """Terminate the game process if running."""
        if self._game_process and self._game_process.poll() is None:
            try:
                self._game_process.kill()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._game_process is not None and self._game_process.poll() is None
