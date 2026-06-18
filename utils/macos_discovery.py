"""macOS game-window discovery.

Pure parsing core for filtering a CGWindowListCopyWindowInfo-shaped list
(list of dicts with string keys) down to game windows. PyObjC imports that
actually query the window server are lazy and added in a later task, so this
module imports cleanly on any platform.
"""

from __future__ import annotations

import dataclasses
import threading
import time

# Snapshot-cache TTL for the (expensive) window-server enumeration. The same
# enumeration feeds the per-keystroke suppression-classification path (pynput
# tap thread, via get_game_for_window) AND the ~250ms window poll, so caching it
# briefly collapses what was a per-keystroke + N+1-per-poll storm of
# CGWindowListCopyWindowInfo calls into roughly one call per TTL.
_ENUM_TTL = 0.5
_enum_lock = threading.Lock()
_enum_cache = {"t": -1.0, "recs": []}

# Owner-name startswith markers mapped to a game tag. Window titles are NOT
# used for matching because reading them may require Screen Recording
# permission; owner (application) names are available without it.
#
# Owner name alone is ambiguous: the TTR game ENGINE and the Toontown LAUNCHER
# both run under owner name "Toontown Rewritten", so this prefix match counts the
# launcher (and any login/news/patch window) as a game window. The records are
# therefore refined by bundle id after enumeration (see _refine_game): bundle ids
# come from NSRunningApplication and are readable WITHOUT Screen Recording.
_GAME_MARKERS = (
    ("Toontown Rewritten", "ttr"),
    ("Corporate Clash", "cc"),
)

# Authoritative engine bundle ids -> game tag. A window owned by one of these is
# definitively that game's engine (not a launcher/updater). Permission-free and
# stable. Corporate Clash has no known NATIVE macOS engine bundle (it runs under
# Wine / is unsupported on macOS), so it is intentionally absent and falls back
# to owner-name identification.
_ENGINE_BUNDLE_IDS = {
    "com.toontownrewritten.engine": "ttr",
}

# Games for which we have an authoritative engine bundle id. For these, a
# RESOLVED non-engine bundle under the same owner name is NOT the game window
# (strict: "only the real game window"). Kept in sync with _ENGINE_BUNDLE_IDS.
_STRICT_BUNDLE_GAMES = frozenset(_ENGINE_BUNDLE_IDS.values())


def _is_launcher_bundle(bundle_id) -> bool:
    """True if the bundle id looks like a game LAUNCHER/updater (never a game
    window). Tokenized rather than a raw 'launcher' substring so unrelated ids
    like 'com.x.relauncherator' are not falsely matched."""
    if not bundle_id:
        return False
    b = bundle_id.lower()
    return (
        b.endswith("launcher")
        or ".launcher" in b
        or "-launcher" in b
        or "_launcher" in b
    )


def _refine_game(candidate_game, bundle_id):
    """Refine an owner-name game candidate using its resolved bundle id.

    Returns the game tag to keep, or None to reject the window. Policy:
      - a known engine bundle is authoritatively that game (wins outright);
      - a launcher/updater bundle is never a game window;
      - for a game WITH an authoritative engine id, a resolved non-engine bundle
        is rejected (strict);
      - bundle_id is None (NSRunningApplication could not resolve it) fails OPEN
        to the owner-name candidate, so a transient resolver miss never strands
        the real game;
      - otherwise trust the owner-name candidate (e.g. Corporate Clash).
    """
    eng = _ENGINE_BUNDLE_IDS.get(bundle_id) if bundle_id else None
    if eng is not None:
        return eng
    if _is_launcher_bundle(bundle_id):
        return None
    if candidate_game in _STRICT_BUNDLE_GAMES and bundle_id is not None:
        return None
    return candidate_game


def _refine_records(records, bundle_id_fn):
    """Refine owner-name candidate records by bundle id: drop launchers / non-game
    windows and stamp survivors with their resolved bundle id. bundle_id_fn maps a
    pid -> bundle id (or None); injected so the pipeline is unit-testable."""
    out = []
    for r in records:
        bid = bundle_id_fn(r.pid)
        game = _refine_game(r.game, bid)
        if game is None:
            continue
        out.append(dataclasses.replace(r, game=game, bundle_id=bid))
    return out


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


def _reset_enum_cache() -> None:
    """Invalidate the enumeration snapshot cache (tests / explicit refresh)."""
    with _enum_lock:
        _enum_cache["t"] = -1.0
        _enum_cache["recs"] = []


def _raw_window_info() -> list:
    """Raw CGWindowListCopyWindowInfo dicts for on-screen, non-desktop windows.

    Isolated as a seam so the identify + bundle-id refine pipeline is unit-testable
    without touching the live window server."""
    Q = _quartz()
    import objc
    with objc.autorelease_pool():
        opts = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
        return list(Q.CGWindowListCopyWindowInfo(opts, Q.kCGNullWindowID) or [])


def _enumerate_game_windows_uncached() -> list:
    """Live GameWindow records (bundle-id refined) from the on-screen window list.

    Owner-name candidates from identify_game_windows() are refined by bundle id so
    launchers/updaters (which share a game's owner name) are excluded; see
    _refine_game. Returns [] on any error. This honors the same contract as
    x11_discovery: discovery query functions never raise, so callers like
    window_manager's poll/refresh_geometry loop and game_registry are crash-safe."""
    try:
        info = _raw_window_info()
        return _refine_records(identify_game_windows(info), process_bundle_id)
    except Exception:
        return []


def _enumerate_game_windows() -> list:
    """Cached snapshot of the on-screen game windows (see _ENUM_TTL).

    The lock guards only the fast cache dict ops; the slow enumeration runs
    OUTSIDE the lock so the pynput tap thread never blocks on the poll thread's
    in-flight enumeration. A simultaneous cache miss on both threads just
    enumerates twice (harmless). Never raises (the uncached core returns [])."""
    started = time.monotonic()
    with _enum_lock:
        if started - _enum_cache["t"] <= _ENUM_TTL:
            return _enum_cache["recs"]
    recs = _enumerate_game_windows_uncached()
    with _enum_lock:
        # Stamp with the snapshot's START time and publish only if this snapshot
        # is at least as new as the cached one. Otherwise a slow OLDER-started
        # enumeration that finishes after a newer one would both clobber the
        # newer snapshot AND restart its TTL, serving stale data past _ENUM_TTL.
        if started >= _enum_cache["t"]:
            _enum_cache["t"] = started
            _enum_cache["recs"] = recs
        return _enum_cache["recs"]


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
    """Out of scope for v1 click-sync (the safe active-window resolver is used
    instead; see active_source_window). Returns None."""
    return None


def get_window_geometry_fresh(wid):
    """LIVE (uncached) content-rect for a single game window, or None. Click-sync
    gesture snapshots use this at press time so a moved-then-clicked window does not
    map against a stale (cached) origin. TTR is borderless, so kCGWindowBounds IS the
    content rect (inset 0); if a future build adds a title bar, subtract the inset HERE."""
    for r in _enumerate_game_windows_uncached():
        if str(r.window_id) == str(wid):
            return r.bounds
    return None


def active_source_window(root_x, root_y, member_wids, *, active_fn=None, geom_fn=None):
    """Safe active-window source resolver (spec §3.4): the frontmost game window must
    be a synced MEMBER and the point must lie inside its FRESH geometry, else None.
    The private key-flip never changes the system front process, so the active window
    stays a reliable source signal. `active_fn`/`geom_fn` are injectable for tests."""
    active_fn = active_fn or get_active_window_id
    geom_fn = geom_fn or get_window_geometry_fresh
    active = active_fn()
    if active is None or str(active) not in [str(w) for w in member_wids]:
        return None
    g = geom_fn(active)
    if g and g[0] <= root_x < g[0] + g[2] and g[1] <= root_y < g[1] + g[3]:
        return active
    return None
