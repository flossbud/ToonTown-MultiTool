"""
TTR Launcher Service — handles launching the actual TTREngine process
and monitoring its lifecycle (PID, exit code).
"""

import os
import subprocess
import threading
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
    game_exited = Signal(int)       # (return_code)
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

        # Ensure executable
        if not os.access(engine_path, os.X_OK):
            try:
                os.chmod(engine_path, 0o755)
            except Exception:
                pass

        env = build_launcher_env({
            "TTR_GAMESERVER": gameserver,
            "TTR_PLAYCOOKIE": cookie,
        })

        def _run():
            try:
                import sys
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

                self._game_process = host_popen(
                    [engine_path],
                    cwd=engine_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **kwargs
                )
                pid = self._game_process.pid
                GameRegistry.instance().register(pid, "ttr")
                self.game_launched.emit(pid)

                # Wait for game to exit
                retcode = self._game_process.wait()
                GameRegistry.instance().unregister(pid)
                self._game_process = None
                self.game_exited.emit(retcode)

            except Exception as e:
                self.launch_failed.emit(f"Launch error: {e}")

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
