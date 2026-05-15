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
from services.cc_login_service import CC_ENGINE_SEARCH_PATHS
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

    def launch(self, gameserver: str, game_token: str, install):
        """Launch CorporateClash for a discovered install.

        Parameters
        ----------
        gameserver : str
            -g <gameserver> CLI arg; empty string omits it.
        game_token : str
            Per-launch game token from the launcher API /login response;
            passed to the game via the CC_OSST_TOKEN env var.
        install : services.wine_runtimes.WineInstall
            Discovered install. Caller is responsible for classification.
        """
        from services.wine_runtimes import (
            build_launch_command, is_launcher_available,
        )

        print(f"[CCLauncher] launch: gameserver='{gameserver}' "
              f"token_len={len(game_token) if game_token else 0} "
              f"install.launcher={install.launcher!r} "
              f"install.exe_path={install.exe_path!r} "
              f"install.prefix_path={install.prefix_path!r}")

        if not os.path.isfile(install.exe_path):
            print(f"[CCLauncher] launch: exe_path NOT a file; aborting")
            self.launch_failed.emit(
                f"CorporateClash not found at {install.exe_path}"
            )
            return

        if not _is_trusted(install, self.settings_manager):
            print(f"[CCLauncher] launch: install NOT trusted; aborting")
            self.launch_failed.emit(
                "CorporateClash path is not in the trusted install list. "
                "Re-select it in Settings to approve a custom install."
            )
            return

        if not is_launcher_available(install.launcher):
            print(f"[CCLauncher] launch: launcher '{install.launcher}' NOT available; aborting")
            self.launch_failed.emit(
                self._availability_error_message(install.launcher)
            )
            return

        args: list[str] = []
        if gameserver:
            args.extend(["-g", gameserver])
        extra_env: dict[str, str] = {}
        if game_token:
            extra_env["CC_OSST_TOKEN"] = game_token

        try:
            cmd, env_overrides = build_launch_command(install, args, extra_env)
        except ValueError as e:
            print(f"[CCLauncher] launch: build_launch_command ValueError {e}")
            self.launch_failed.emit(f"Cannot build launch command: {e}")
            return

        spawn_env = build_launcher_env(env_overrides)
        cwd = install.prefix_path or os.path.dirname(install.exe_path)
        safe_env_keys = sorted(k for k in env_overrides if k != "CC_OSST_TOKEN")
        print(f"[CCLauncher] launch: cmd={cmd}")
        print(f"[CCLauncher] launch: cwd={cwd}")
        print(f"[CCLauncher] launch: env_overrides keys={safe_env_keys} "
              f"+ CC_OSST_TOKEN(masked)={'present' if 'CC_OSST_TOKEN' in env_overrides else 'absent'}")

        def _run():
            try:
                import sys
                kwargs = {}
                if sys.platform == "win32" and install.launcher == "native":
                    kwargs["creationflags"] = (
                        subprocess.DETACHED_PROCESS
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_BREAKAWAY_FROM_JOB
                    )

                def _spawn():
                    return host_popen(
                        cmd,
                        cwd=cwd,
                        env=spawn_env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        **kwargs,
                    )

                print(f"[CCLauncher] _run: spawning…")
                try:
                    self._game_process = _spawn()
                except OSError as e:
                    if sys.platform != "win32" or getattr(e, "winerror", None) != 5:
                        raise
                    kwargs["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
                    self._game_process = _spawn()
                pid = self._game_process.pid
                print(f"[CCLauncher] _run: spawned pid={pid}")
                GameRegistry.instance().register(pid, "cc")
                self.game_launched.emit(pid)

                retcode = self._game_process.wait()
                print(f"[CCLauncher] _run: child exited rc={retcode}")
                GameRegistry.instance().unregister(pid)
                self._game_process = None
                self.game_exited.emit(retcode)

            except Exception as e:
                print(f"[CCLauncher] _run: error {type(e).__name__}: {e}")
                self.launch_failed.emit(f"Launch error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _availability_error_message(launcher: str) -> str:
        messages = {
            "bottles": (
                "Detected Corporate Clash inside Bottles, but bottles-cli is "
                "not available on this system. Install Bottles or pick a "
                "different install in Settings."
            ),
            "lutris": (
                "Detected Corporate Clash in a Lutris-managed prefix, but the "
                "wine binary is not available. Install wine or pick a "
                "different install in Settings."
            ),
            "steam-proton": (
                "Detected Corporate Clash in a Steam Proton prefix, but Steam "
                "is not available. Launch Steam or pick a different install."
            ),
            "wine": (
                "Detected Corporate Clash in a Wine prefix, but the wine "
                "binary is not available. Install wine or pick a different "
                "install in Settings."
            ),
        }
        return messages.get(
            launcher,
            f"Required runtime for launcher '{launcher}' is not available.",
        )

    def kill(self):
        """Terminate the game process if running."""
        if self._game_process and self._game_process.poll() is None:
            try:
                self._game_process.kill()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._game_process is not None and self._game_process.poll() is None
