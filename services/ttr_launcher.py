"""
TTR Launcher Service — handles launching the actual TTREngine process
and monitoring its lifecycle (PID, exit code).
"""

import os
import subprocess
import threading
from PySide6.QtCore import QObject, Signal

class TTRLauncher(QObject):
    game_launched = Signal(int)     # (pid)
    game_exited = Signal(int)       # (return_code)
    launch_failed = Signal(str)     # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game_process = None

    def launch(self, gameserver: str, cookie: str, engine_dir: str):
        """Launch TTREngine with credentials in a background thread."""
        engine_path = os.path.join(engine_dir, "TTREngine")

        if not os.path.isfile(engine_path):
            self.launch_failed.emit(f"TTREngine not found at {engine_path}")
            return

        # Ensure executable
        if not os.access(engine_path, os.X_OK):
            try:
                os.chmod(engine_path, 0o755)
            except Exception:
                pass

        env = os.environ.copy()
        env["TTR_GAMESERVER"] = gameserver
        env["TTR_PLAYCOOKIE"] = cookie

        def _run():
            try:
                self._game_process = subprocess.Popen(
                    [engine_path],
                    cwd=engine_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.game_launched.emit(self._game_process.pid)

                # Wait for game to exit
                retcode = self._game_process.wait()
                self._game_process = None
                self.game_exited.emit(retcode)

            except Exception as e:
                self.launch_failed.emit(f"Launch error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def kill(self):
        """Terminate the game process if running."""
        if self._game_process and self._game_process.poll() is None:
            try:
                self._game_process.terminate()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._game_process is not None and self._game_process.poll() is None
