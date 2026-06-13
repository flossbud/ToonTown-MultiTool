"""
Game Registry — maps running game PIDs to their game type ("ttr" or "cc").

Written to by launchers at launch time. Read by the multitoon tab during refresh
to determine which API to call for each window. Thread-safe.

For windows launched outside of TTMT, a process-name fallback table is used
to identify the game from the executable name.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

_KNOWN_PROCESSES = {
    "ttrengine64.exe": "ttr",
    "ttrengine":       "ttr",
    "corporateclash.exe": "cc",
    "corporateclash":    "cc",
}

# X11 WM_CLASS values for each supported game. Used as the last-ditch fallback
# in Flatpak installs, where /proc/<host_pid>/exe is unreadable because the
# sandbox's PID namespace differs from the host's. Values are lowercased
# before comparison.
_KNOWN_X11_CLASSES = {
    "toontown rewritten": "ttr",
    "corporate clash":    "cc",
}

# Linux helper executables that host a Windows game under Wine/Proton. When
# /proc/<pid>/exe resolves to one of these, the X-client PID is a wine
# infrastructure process, not the game — so look at argv[0] from cmdline
# (the Windows-style path to the .exe Wine is hosting) instead.
_KNOWN_WINE_HELPERS = {
    "wine-preloader",
    "wine64-preloader",
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

        Falls back to process-name identification for externally-launched windows,
        then to argv[0] inspection when the process is a Wine helper hosting a
        Windows .exe (the CC-on-Linux case: exe=wine64-preloader,
        argv[0]=...\\CorporateClash.exe), and finally to X11 WM_CLASS when /proc
        lookups fail (e.g. inside Flatpak, where the sandbox PID namespace
        makes /proc/<host_pid>/exe unreadable).
        """
        pid = self._get_pid_for_window(wid)
        if pid is not None:
            game = self.get_game(pid)
            if game is not None:
                return game

            by_name = self._tag_from_process_name(pid)
            if by_name is not None:
                return by_name

            by_wine = self._tag_from_wine_cmdline(pid)
            if by_wine is not None:
                return by_wine

        if sys.platform == "darwin":
            from utils import macos_discovery
            return macos_discovery.game_for_window_id(wid)
        if sys.platform != "win32":
            return self._tag_from_x11_class(wid)
        return None

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
        if sys.platform == "win32" or sys.platform == "darwin":
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
        by_name = _KNOWN_PROCESSES.get(name)
        if by_name is not None:
            return by_name, True
        # Wine/Proton case: exe is a wine preloader; the game identity lives
        # in argv[0]. Without this branch the trust filter rejects every
        # Proton-launched CC window as "confirmed not a game".
        if name in _KNOWN_WINE_HELPERS:
            by_wine = self._tag_from_wine_cmdline(pid)
            if by_wine is not None:
                return by_wine, True
        return None, True

    @staticmethod
    def _get_pid_for_window(wid: str) -> int | None:
        """Resolve a window ID to a PID using platform APIs."""
        try:
            if sys.platform == "win32":
                import win32process
                hwnd = int(wid)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                return pid
            if sys.platform == "darwin":
                from utils import macos_discovery
                return macos_discovery.get_window_pid(wid)
            else:
                # Prefer XRes host PID to avoid Flatpak namespace PID mismatches.
                host_pid = GameRegistry._get_host_pid_for_window_xres(wid)
                if host_pid is not None:
                    return host_pid
                from utils import x11_discovery
                return x11_discovery.get_window_pid(wid)
        except Exception:
            return None

    @staticmethod
    def _get_host_pid_for_window_xres(wid: str) -> int | None:
        """Resolve a Linux window ID to host PID via XRes when available.

        Uses x11_discovery's per-thread cached Display rather than opening
        a fresh connection: callers include the WindowManager poll thread
        (via classify_window_for_filtering, hit per candidate window per
        2-second sweep) and constructing a Display per call hammered the
        Python 3.14 GC. See [[project_py314_pyside6_gc_paint_race]].
        """
        try:
            from Xlib.ext import res as xres
            from utils import x11_discovery

            d = x11_discovery._open_display()
            if d is None:
                return None
            if not d.has_extension("X-Resource"):
                return None
            resp = d.res_query_client_ids(
                [{"client": int(wid), "mask": xres.LocalClientPIDMask}]
            )
            for cid in resp.ids:
                if cid.value:
                    return int(cid.value[0])
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
    def _tag_from_wine_cmdline(pid: int) -> str | None:
        """Identify a Wine/Proton-hosted game by inspecting argv[0].

        Under Wine, /proc/<pid>/exe points at the preloader binary (e.g.
        wine64-preloader) for every Windows program — the actual game
        identity is only in argv[0], which holds the Windows-style path Wine
        was asked to launch (e.g. r"C:\\users\\steamuser\\AppData\\Local\\
        Corporate Clash\\CorporateClash.exe"). We extract the trailing
        basename and look it up in _KNOWN_PROCESSES.

        Returns None on non-Linux, when /proc is unreadable, when the
        process isn't a wine helper, or when argv[0]'s basename is unknown.
        """
        if sys.platform == "win32":
            return None
        name = GameRegistry._get_process_name(pid)
        if name not in _KNOWN_WINE_HELPERS:
            return None
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read()
        except OSError:
            return None
        argv0 = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        if not argv0:
            return None
        # argv[0] is a Windows path; backslashes are the separator. Splitting
        # on both lets us handle the rare Wine path that's been normalized.
        basename = argv0.replace("\\", "/").rsplit("/", 1)[-1].lower()
        return _KNOWN_PROCESSES.get(basename)

    @staticmethod
    def _tag_from_x11_class(wid: str) -> str | None:
        """Identify a game by the window's X11 WM_CLASS.

        This is the Flatpak sandbox fallback: WM_CLASS is set by the game and
        is visible to any X11 client, unlike /proc/<host_pid>/exe which is
        gated by the PID namespace. Returns None on non-X11 systems or when
        the class is missing/unknown.
        """
        try:
            from utils import x11_discovery

            d = x11_discovery._open_display()
            if d is None:
                return None
            win = d.create_resource_object("window", int(wid))
            wm_class = win.get_wm_class()
        except Exception:
            return None
        if not wm_class:
            return None
        # WM_CLASS is a (instance, class) tuple; check both, lowercased.
        for token in wm_class:
            if not token:
                continue
            tag = _KNOWN_X11_CLASSES.get(token.lower())
            if tag is not None:
                return tag
        return None

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
                    logger.warning("Win32 process query failed for PID %d: %s", pid, e)
                    return None
                finally:
                    win32api.CloseHandle(handle)
            else:
                exe = os.readlink(f"/proc/{pid}/exe")
        except (OSError, FileNotFoundError) as e:
            if getattr(e, "errno", None) in (errno.EACCES, errno.EPERM, errno.ENOENT):
                logger.debug("Process name lookup failed for PID %d: %s", pid, e)
            else:
                logger.warning("Process name lookup failed for PID %d: %s", pid, e)
            return None
        return os.path.basename(exe).lower()
