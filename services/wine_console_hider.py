"""Hides the Wine console window that Corporate Clash's TTCCLauncher spawns
via AllocConsole(). The console shows CC's stdout (font loads, downloader
status, ConfigVariable changes) and is useful for debugging but visual
noise in the common-case successful launch.

After CCLauncher emits `game_launched`, this module polls top-level X11
windows every WATCH_INTERVAL_MS for up to WATCH_DURATION_MS, unmapping any
window whose title (case- and slash-normalized) ends with the CC exe
basename. The console process remains alive (CC's stdout keeps flowing);
only its X11 surface vanishes.

Single-shot per launch. Gated by the CC_HIDE_LAUNCH_CONSOLE setting
(default True). See docs/superpowers/specs/2026-05-21-hide-cc-launch-
console-design.md for the full design rationale.
"""

from __future__ import annotations

# Suffix the title must end with (after lowercasing and replacing forward
# slashes with backslashes). The leading backslash anchors against the
# Windows path separator so a token like "foo-corporateclash.exe.txt"
# never matches.
_CONSOLE_TITLE_SUFFIX = r"\corporateclash.exe"

# Polling cadence in milliseconds. 200ms is short enough that the user
# rarely perceives the console flash; long enough that 75 ticks over
# WATCH_DURATION_MS is trivial CPU.
WATCH_INTERVAL_MS = 200

# Total time to keep polling per launch. 15s covers CC's cold-start
# (network-bound) without leaving the timer running indefinitely.
WATCH_DURATION_MS = 15_000


def _title_matches(title: str) -> bool:
    """True if a window title looks like the Wine console for CC's exe.

    Normalization: lowercase, then replace forward slashes with backslashes
    so `C:/users/.../CorporateClash.exe` is treated the same as
    `C:\\users\\...\\CorporateClash.exe`. Match anchored on the leading
    backslash to prevent false positives on `*corporateclash.exe.txt` or
    `foo-corporateclash.exe` substrings.
    """
    if not title:
        return False
    normalized = title.lower().replace("/", "\\")
    return normalized.endswith(_CONSOLE_TITLE_SUFFIX)


from typing import Callable, Iterable, Tuple

from PySide6.QtCore import QObject, QTimer

from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE


# Enumerator: zero-arg callable returning iterable of (wid_int, title_str).
EnumeratorFn = Callable[[], Iterable[Tuple[int, str]]]
# Unmapper: takes a window-id int, returns None. May raise; caller swallows.
UnmapperFn = Callable[[int], None]


def _real_enumerator() -> list[tuple[int, str]]:
    """Walk the X11 window tree and yield (wid, title) for every window
    that has a title set. Title resolution prefers _NET_WM_NAME with
    WM_NAME fallback, mirroring utils.x11_discovery._walk_collect.

    Returns an empty list if Xlib can't open a display (headless test box,
    Windows host, etc.); never raises.
    """
    try:
        from Xlib import display as xdisplay  # type: ignore
    except Exception:
        return []
    d = None
    try:
        d = xdisplay.Display()
        root = d.screen().root
        out: list[tuple[int, str]] = []
        _walk_titles(root, out)
        return out
    except Exception:
        return []
    finally:
        if d is not None:
            try:
                d.close()
            except Exception:
                pass


def _walk_titles(window, out: list[tuple[int, str]]) -> None:
    """Recursively collect (wid, title) for every window with a title."""
    try:
        name = window.get_wm_name()
    except Exception:
        name = None
    if name:
        out.append((int(window.id), str(name)))
    try:
        children = window.query_tree().children
    except Exception:
        children = []
    for child in children:
        _walk_titles(child, out)


def _real_unmapper(wid: int) -> None:
    """Issue XUnmapWindow on `wid`. Opens a fresh display per call to
    avoid cross-thread Display sharing; matches utils.x11_discovery pattern."""
    try:
        from Xlib import display as xdisplay  # type: ignore
    except Exception:
        return
    d = None
    try:
        d = xdisplay.Display()
        # Create a Window object bound to the existing wid and unmap it.
        win = d.create_resource_object("window", wid)
        win.unmap()
        d.flush()
    except Exception:
        return
    finally:
        if d is not None:
            try:
                d.close()
            except Exception:
                pass


class WineConsoleHider(QObject):
    """Listens for CCLauncher.game_launched and unmaps the spawned Wine
    console. See module docstring for the full rationale."""

    def __init__(
        self,
        settings_manager,
        *,
        enumerator: EnumeratorFn | None = None,
        unmapper: UnmapperFn | None = None,
        timer_factory=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_manager
        self._enumerate: EnumeratorFn = enumerator or _real_enumerator
        self._unmap: UnmapperFn = unmapper or _real_unmapper

        if timer_factory is None:
            timer = QTimer(self)
            timer.setInterval(WATCH_INTERVAL_MS)
            timer.timeout.connect(self._tick)
        else:
            timer = timer_factory()
            timer.setInterval(WATCH_INTERVAL_MS)
            # Test timers expose a `timeout_connect` shim because QTimer's
            # `timeout` is a Qt signal that the fake doesn't replicate.
            if hasattr(timer, "timeout_connect"):
                timer.timeout_connect(self._tick)
            else:
                timer.timeout.connect(self._tick)
        self._timer = timer

        self._max_ticks = WATCH_DURATION_MS // WATCH_INTERVAL_MS
        self._tick_count = 0
        self._already_unmapped: set[int] = set()

    def attach(self, cc_launcher) -> None:
        """Connect to a CCLauncher's game_launched signal. Idempotent at
        the per-launcher level: each new CCLauncher should have attach()
        called once."""
        cc_launcher.game_launched.connect(self.on_game_launched)

    def on_game_launched(self, pid: int) -> None:
        """Slot: game spawned. (Re)start the polling timer if enabled."""
        if not self._settings.get(CC_HIDE_LAUNCH_CONSOLE, True):
            return
        # Reset per-launch state. A second launch arriving during a watch
        # window restarts the budget from zero, so multi-account launches
        # all get the full 15s coverage.
        self._tick_count = 0
        self._already_unmapped.clear()
        self._timer.start()

    def _tick(self) -> None:
        """Polling tick: enumerate windows, unmap any new matches, stop
        the timer after _max_ticks."""
        self._tick_count += 1
        try:
            windows = list(self._enumerate())
        except Exception as e:
            print(f"[WineConsoleHider] enumerator error: {e}")
            windows = []
        for wid, title in windows:
            if wid in self._already_unmapped:
                continue
            if not _title_matches(title):
                continue
            try:
                self._unmap(wid)
                print(
                    f"[WineConsoleHider] hid console "
                    f"wid={hex(wid)} title={title!r}"
                )
            except Exception as e:
                print(f"[WineConsoleHider] unmap error wid={hex(wid)}: {e}")
            # Record even on failure so we don't retry the same wid every tick.
            self._already_unmapped.add(wid)
        if self._tick_count >= self._max_ticks:
            self._timer.stop()
            if not self._already_unmapped:
                print("[WineConsoleHider] no console seen in 15s; giving up")
