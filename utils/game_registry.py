"""
Game Registry — maps running game PIDs to their game type ("ttr" or "cc").

Written to by launchers at launch time. Read by the multitoon tab during refresh
to determine which API to call for each window. Thread-safe.

For windows launched outside of TTMT, a process-name fallback table is used
to identify the game from the executable name.
"""

import os
import sys
import threading

_KNOWN_PROCESSES = {
    "ttrengine64.exe": "ttr",
    "ttrengine":       "ttr",
    "corporateclash.exe": "cc",
    "corporateclash":    "cc",
}


class GameRegistry:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._pid_to_game: dict[int, str] = {}
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "GameRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, pid: int, game: str):
        """Record that a launched process belongs to a specific game."""
        with self._lock:
            self._pid_to_game[pid] = game

    def unregister(self, pid: int):
        """Remove a process from the registry (called on exit)."""
        with self._lock:
            self._pid_to_game.pop(pid, None)

    def get_game(self, pid: int) -> str | None:
        """Return the game tag for a PID, or None if unknown."""
        with self._lock:
            return self._pid_to_game.get(pid)

    def get_game_for_window(self, wid: str) -> str | None:
        """Look up the game tag for a window ID by resolving its PID first.

        Falls back to process-name identification for externally-launched windows.
        """
        pid = self._get_pid_for_window(wid)
        if pid is None:
            return None

        game = self.get_game(pid)
        if game is not None:
            return game

        # Fallback: check the process executable name
        return self._tag_from_process_name(pid)

    def classify_window_for_filtering(self, wid: str) -> tuple[str | None, bool]:
        """Classify a window for additive trust filtering.

        Returns ``(game, confirmed)``:
        - ``confirmed=False`` means process identity could not be established
          reliably enough to reject the window, so callers should keep their
          existing title/class heuristics.
        - ``confirmed=True`` with ``game is None`` means the process identity
          was resolved and it is not a known supported game.

        On Linux this only uses the XRes host PID path; the xdotool PID fallback
        is intentionally excluded here because namespace PID mismatches can make
        it unsuitable for negative trust decisions on Flatpak installs.
        """
        if sys.platform == "win32":
            pid = self._get_pid_for_window(wid)
        else:
            pid = self._get_host_pid_for_window_xres(wid)
        if pid is None:
            return None, False

        game = self.get_game(pid)
        if game is not None:
            return game, True

        name = self._get_process_name(pid)
        if name is None:
            return None, False
        return _KNOWN_PROCESSES.get(name), True

    @staticmethod
    def _get_pid_for_window(wid: str) -> int | None:
        """Resolve a window ID to a PID using platform APIs."""
        try:
            if sys.platform == "win32":
                import win32process
                hwnd = int(wid)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                return pid
            else:
                # Prefer XRes host PID to avoid Flatpak namespace PID mismatches.
                host_pid = GameRegistry._get_host_pid_for_window_xres(wid)
                if host_pid is not None:
                    return host_pid
                import subprocess
                pid_str = subprocess.check_output(
                    ["xdotool", "getwindowpid", wid],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                return int(pid_str)
        except Exception:
            return None

    @staticmethod
    def _get_host_pid_for_window_xres(wid: str) -> int | None:
        """Resolve a Linux window ID to host PID via XRes when available."""
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import res as xres

            d = xdisplay.Display()
            try:
                if not d.has_extension("X-Resource"):
                    return None
                resp = d.res_query_client_ids(
                    [{"client": int(wid), "mask": xres.LocalClientPIDMask}]
                )
                for cid in resp.ids:
                    if cid.value:
                        return int(cid.value[0])
            finally:
                d.close()
        except Exception:
            return None
        return None

    @staticmethod
    def _tag_from_process_name(pid: int) -> str | None:
        """Identify a game by its process executable name."""
        name = GameRegistry._get_process_name(pid)
        if name is None:
            return None
        return _KNOWN_PROCESSES.get(name)

    @staticmethod
    def _get_process_name(pid: int) -> str | None:
        """Return the lowercase executable basename for a PID."""
        try:
            if sys.platform == "win32":
                import win32api
                import win32process
                import win32con
                handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                try:
                    exe = win32process.GetModuleFileNameEx(handle, 0)
                except (OSError, AttributeError) as e:
                    print(f"[GameRegistry] Win32 process query failed for PID {pid}: {e}")
                    return None
                finally:
                    win32api.CloseHandle(handle)
            else:
                exe = os.readlink(f"/proc/{pid}/exe")
        except (OSError, FileNotFoundError) as e:
            print(f"[GameRegistry] Process name lookup failed for PID {pid}: {e}")
            return None
        return os.path.basename(exe).lower()
