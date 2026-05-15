"""
Corporate Clash Launcher Service — handles launching the CorporateClash process
and monitoring its lifecycle (PID, exit code).

Key differences from TTRLauncher:
  - Uses CLI arg (-g gameserver) and env var (CC_OSST_TOKEN) for credentials
  - Different trusted install roots
  - Different binary name
"""

from __future__ import annotations

import os
import subprocess
import threading
from PySide6.QtCore import QObject, Signal
from services.cc_login_service import CC_ENGINE_SEARCH_PATHS, get_cc_engine_executable_name
from services.launcher_env import build_launcher_env
from services.wine_runtimes import WineInstall
from utils.game_registry import GameRegistry
from utils.host_spawn import host_popen

_CUSTOM_APPROVAL_KEY = "cc_engine_dir_approved_custom_dir"


def _approved_custom_engine_dir(settings_manager) -> str | None:
    if settings_manager is None:
        return None
    approved = settings_manager.get(_CUSTOM_APPROVAL_KEY, "")
    return os.path.realpath(approved) if approved else None


def _is_trusted(install: WineInstall, settings_manager) -> bool:
    """Return True when this install is auto-trusted or explicitly approved.

    Discovery-via-known-launcher is the trust signal: classify_path /
    discover_* only build a non-native WineInstall after observing
    structural markers (bottle.yml, compatdata layout, dosdevices/c:, etc.).
    """
    if install.launcher in ("bottles", "lutris", "steam-proton", "wine"):
        return True
    if install.launcher == "native":
        engine_dir = os.path.realpath(os.path.dirname(install.exe_path))
        trusted = {os.path.realpath(p) for p in CC_ENGINE_SEARCH_PATHS}
        if engine_dir in trusted:
            return True
    approved = _approved_custom_engine_dir(settings_manager)
    return bool(
        approved
        and os.path.realpath(os.path.dirname(install.exe_path)) == approved
    )


class CCLauncher(QObject):
    game_launched = Signal(int)     # (pid)
    game_exited = Signal(int)       # (return_code)
    launch_failed = Signal(str)     # (error_message)

    def __init__(self, parent=None, settings_manager=None):
        super().__init__(parent)
        self._game_process = None
        self.settings_manager = settings_manager

    def launch(self, gameserver: str, osst_token: str, engine_dir: str):
        """Launch CorporateClash with credentials in a background thread."""
        binary_name = get_cc_engine_executable_name()
        engine_path = os.path.join(engine_dir, binary_name)

        if not os.path.isfile(engine_path):
            self.launch_failed.emit(f"CorporateClash not found at {engine_path}")
            return

        if not _is_trusted_cc_engine_path(engine_path, self.settings_manager):
            self.launch_failed.emit(
                "CorporateClash path is not in the trusted install list. "
                "Re-select it in Settings to approve a custom install."
            )
            return

        # Ensure executable (Linux/Wine)
        if not os.access(engine_path, os.X_OK):
            try:
                os.chmod(engine_path, 0o755)
            except Exception:
                pass

        def _run():
            try:
                import sys
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

                cmd = [engine_path]
                if gameserver:
                    cmd.extend(["-g", gameserver])

                # Pass token via env var to avoid exposure in ps / /proc/[pid]/cmdline
                extra_env = {}
                if osst_token:
                    extra_env["CC_OSST_TOKEN"] = osst_token

                spawn_env = build_launcher_env(extra_env)

                def _spawn():
                    return host_popen(
                        cmd,
                        cwd=engine_dir,
                        env=spawn_env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
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
                GameRegistry.instance().register(pid, "cc")
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
