"""macOS game-window discovery.

Pure parsing core for filtering a CGWindowListCopyWindowInfo-shaped list
(list of dicts with string keys) down to game windows. PyObjC imports that
actually query the window server are lazy and added in a later task, so this
module imports cleanly on any platform.
"""

from __future__ import annotations

import dataclasses

# Owner-name startswith markers mapped to a game tag. Window titles are NOT
# used for matching because reading them may require Screen Recording
# permission; owner (application) names are available without it.
_GAME_MARKERS = (
    ("Toontown Rewritten", "ttr"),
    ("Corporate Clash", "cc"),
)


@dataclasses.dataclass(frozen=True)
class GameWindow:
    pid: int
    window_id: int
    game: str
    owner: str
    bounds: tuple  # (x, y, w, h)
    bundle_id: str | None = None


def identify_game_windows(window_info) -> list:
    """Filter a CGWindowListCopyWindowInfo-shaped list down to game windows."""
    games = []
    for entry in window_info:
        # A single malformed record (null/non-numeric values, missing Bounds)
        # must never abort the whole scan - skip just the bad entry.
        try:
            owner = entry.get("kCGWindowOwnerName") or ""
            game = next(
                (tag for marker, tag in _GAME_MARKERS if owner.startswith(marker)),
                None,
            )
            if game is None:
                continue

            pid = entry.get("kCGWindowOwnerPID")
            number = entry.get("kCGWindowNumber")
            if pid is None or number is None:
                continue

            bounds = entry.get("kCGWindowBounds") or {}
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
            if width <= 0 or height <= 0:
                continue

            games.append(
                GameWindow(
                    pid=int(pid),
                    window_id=int(number),
                    game=game,
                    owner=owner,
                    bounds=(x, y, width, height),
                )
            )
        except (TypeError, ValueError, AttributeError):
            continue
    return games


def _quartz():
    import Quartz
    return Quartz


def process_bundle_id(pid: int):
    """Stable identity for a PID via NSRunningApplication, or None on any error
    (a transient AppKit failure for one PID must not blank the whole window
    enumeration)."""
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return None
        bid = app.bundleIdentifier()
        return str(bid) if bid is not None else None
    except Exception:
        return None


def _enumerate_game_windows() -> list:
    """Live GameWindow records (with bundle_id) from the on-screen window list.

    Returns [] on any error. This honors the same contract as x11_discovery:
    discovery query functions never raise, so callers like window_manager's
    poll/refresh_geometry loop and game_registry are crash-safe."""
    try:
        Q = _quartz()
        import objc
        with objc.autorelease_pool():
            opts = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
            info = Q.CGWindowListCopyWindowInfo(opts, Q.kCGNullWindowID) or []
            recs = identify_game_windows(list(info))
            return [dataclasses.replace(r, bundle_id=process_bundle_id(r.pid)) for r in recs]
    except Exception:
        return []


def find_game_windows() -> list:
    """[(window_id_str, game)] for every on-screen TTR/CC window (matches x11_discovery.find_game_windows())."""
    return [(str(r.window_id), r.game) for r in _enumerate_game_windows()]


def _record_for_wid(wid):
    for r in _enumerate_game_windows():
        if str(r.window_id) == str(wid):
            return r
    return None


def get_window_root_x(wid):
    r = _record_for_wid(wid)
    return r.bounds[0] if r else None


def get_window_geometry(wid):
    r = _record_for_wid(wid)
    return r.bounds if r else None


def get_window_pid(wid):
    r = _record_for_wid(wid)
    return r.pid if r else None


def game_for_window_id(wid):
    """'ttr' | 'cc' | None for a window id, by owner name."""
    r = _record_for_wid(wid)
    return r.game if r else None


def get_active_window_id():
    """CGWindowID (str) of the frontmost app's game window, or None (on no match
    or any error). Focus is the frontmost application's PID (NSWorkspace). Never
    raises, matching x11_discovery's contract."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        fpid = int(app.processIdentifier())
        for r in _enumerate_game_windows():
            if r.pid == fpid:
                return str(r.window_id)
        return None
    except Exception:
        return None


def toplevel_at_point(x, y):
    """Out of scope for keyboard Phase 1 (mouse/click-sync). Returns None."""
    return None
