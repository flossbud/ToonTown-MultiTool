"""X11 window discovery via python-Xlib.

Replaces the xdotool subprocess calls (`search --class`, `getactivewindow`,
`getwindowgeometry`, `getwindowpid`) used by the window manager and the TTR
API client. xdotool was bundled in the Flatpak manifest but was never bundled
in the AppImage, which made multitooning silently fail on hosts that don't
ship xdotool by default (notably Fedora). python-Xlib is already a Linux
dependency for the input backend and XRes PID resolution, so this is a
dependency removal, not addition.

The Display is cached per-thread via threading.local and reused across calls
within the same thread. The original design opened a fresh Display per call
to match xdotool's per-subprocess cost, but Display()'s constructor runs a
synchronous get_keyboard_mapping round-trip and allocates a large reply
object graph, which is far heavier than xdotool's fork+exec. At 10 Hz
polling on Python 3.14 that allocation rate fires the incremental GC
constantly inside Xlib reply parsing, which races with Shiboken's
GIL-release during Qt widget destruction in the paint thread and produces a
mark_stacks SEGV (see [[project_py314_pyside6_gc_paint_race]]). Caching
preserves the original no-cross-thread-sharing contract while removing the
allocation storm.

Callers MUST NOT call `.close()` on the returned Display; the cached
connection lives for the calling thread's lifetime and is reclaimed when
the thread dies (or when the process exits, for daemon threads).
"""

from __future__ import annotations

import sys
import threading


_thread_local = threading.local()


def _open_display():
    """Return a connected Xlib Display or None on failure.

    Cached per-thread: the first call from a given thread opens a real
    Xlib connection and stashes it on a threading.local; subsequent calls
    from the same thread return that same Display. Centralized so the
    platform/import guard and the cache live in one place; callers always
    get either a usable Display or None, never an exception.
    """
    if sys.platform == "win32":
        return None
    cached = getattr(_thread_local, "display", None)
    if cached is not None:
        return cached
    try:
        from Xlib import display as xdisplay  # type: ignore
        d = xdisplay.Display()
    except Exception:
        return None
    _thread_local.display = d
    return d


# Marker -> game. WM_CLASS substring match takes precedence; WM_NAME prefix is
# the fallback for Wine/Proton windows whose WM_CLASS is forced to steam_proton.
_GAME_BY_MARKER = {
    "Toontown Rewritten": "ttr",
    "Corporate Clash": "cc",
}


def _game_for_window_props(wm_class, wm_name) -> str | None:
    """Classify a window as 'ttr'/'cc'/None from its WM_CLASS and WM_NAME.

    wm_class is the tuple returned by Xlib's get_wm_class() — (instance, class);
    we match against its class component (index 1). wm_name is the WM_NAME str.
    WM_CLASS substring wins; WM_NAME must *start with* a marker (so a Wine
    console window titled with the full .exe path does not match).
    """
    if wm_class and len(wm_class) >= 2:
        cls = wm_class[1] or ""
        for marker, game in _GAME_BY_MARKER.items():
            if marker in cls:
                return game
    if wm_name:
        name_str = str(wm_name)
        for marker, game in _GAME_BY_MARKER.items():
            if name_str.startswith(marker):
                return game
    return None


def _drop_if_frame(results, own_index: int, own_matched: bool,
                   descendant_matched: bool) -> None:
    """Remove this window's own match when a descendant also matched.

    A reparenting window manager wraps each client in a frame window that is
    the client's parent, so a match that CONTAINS another match is the frame,
    never the game. Normally frames are invisible to us - they carry no
    WM_CLASS and no WM_NAME - but GNOME/Mutter decorates Xwayland clients from
    a separate helper process (``mutter-x11-frames``) whose frame windows copy
    the client's title onto their own WM_NAME. That trips the WM_NAME-prefix
    fallback in ``_game_for_window_props``, so on GNOME every game window was
    discovered twice: once as the frame, once as the real client.

    Deduping by innermost match (rather than by a WM_STATE probe or a
    ``mutter-x11-frames`` denylist) costs no extra X round trip, needs no
    window-manager cooperation, and still keeps an unreparented or
    override-redirect game window, which has no matching descendant.

    ``own_index`` is where this window's entry was appended BEFORE recursing,
    so descendant entries sit after it and the pop leaves their order intact.
    """
    if own_matched and descendant_matched:
        results.pop(own_index)


def find_window_ids_by_class(
    class_names: list[str],
    title_prefixes: list[str] | None = None,
) -> list[str]:
    """Return X11 window IDs whose WM_CLASS class component substring-matches
    any of ``class_names``, OR whose WM_NAME starts with any of
    ``title_prefixes``.

    The WM_CLASS path mirrors the original ``xdotool search --class`` behavior
    (substring, case-sensitive). The title-prefix path exists for Wine/Proton-
    launched Windows games whose WM_CLASS is forced to ``steam_proton`` (or
    similar) regardless of the underlying .exe — the only X11-visible signal
    of "this is Corporate Clash" is the WM_NAME, e.g.
    ``"Corporate Clash [1.11.17777]"``. We require startswith (not substring)
    so the sibling Wine console window whose title is the .exe's full Windows
    path is not falsely matched.

    Only the innermost match on each branch is returned; a match that contains
    another match is a window-manager frame (see ``_drop_if_frame``).

    Returns window IDs as decimal strings.
    """
    if not class_names and not title_prefixes:
        return []
    d = _open_display()
    if d is None:
        return []
    results: list[str] = []
    targets = tuple(class_names or ())
    prefixes = tuple(title_prefixes or ())
    try:
        root = d.screen().root
    except Exception:
        return []
    _walk_collect(root, targets, prefixes, results)
    return results


def _walk_collect(
    window,
    targets: tuple[str, ...],
    prefixes: tuple[str, ...],
    results: list[str],
) -> bool:
    """Depth-first collect into ``results``; returns whether this subtree
    matched. Keeps only the innermost match per branch - see
    ``_drop_if_frame`` for why an outer match is a window-manager frame."""
    matched = False
    if targets:
        try:
            wm_class = window.get_wm_class()
        except Exception:
            wm_class = None
        if wm_class and len(wm_class) >= 2:
            cls = wm_class[1] or ""
            if any(target in cls for target in targets):
                matched = True
    if not matched and prefixes:
        try:
            wm_name = window.get_wm_name()
        except Exception:
            wm_name = None
        if wm_name:
            name_str = str(wm_name)
            if any(name_str.startswith(p) for p in prefixes):
                matched = True
    own_index = len(results)
    if matched:
        results.append(str(window.id))
    try:
        children = window.query_tree().children
    except Exception:
        children = []
    descendant_matched = False
    for child in children:
        if _walk_collect(child, targets, prefixes, results):
            descendant_matched = True
    _drop_if_frame(results, own_index, matched, descendant_matched)
    return matched or descendant_matched


def find_game_windows() -> list[tuple[str, str]]:
    """Return (window_id, game) for all visible TTR/CC windows.

    game is "ttr" or "cc". Mirrors find_window_ids_by_class' matching (including
    the innermost-match frame rule) but keeps the game identity instead of
    discarding it.
    """
    d = _open_display()
    if d is None:
        return []
    results: list[tuple[str, str]] = []
    try:
        root = d.screen().root
    except Exception:
        return []
    _walk_collect_games(root, results)
    return results


def _walk_collect_games(window, results: list[tuple[str, str]]) -> bool:
    """Depth-first collect into ``results``; returns whether this subtree
    matched. Keeps only the innermost match per branch - see ``_drop_if_frame``
    for why an outer match is a window-manager frame."""
    try:
        wm_class = window.get_wm_class()
    except Exception:
        wm_class = None
    try:
        wm_name = window.get_wm_name()
    except Exception:
        wm_name = None
    game = _game_for_window_props(wm_class, wm_name)
    own_index = len(results)
    if game is not None:
        results.append((str(window.id), game))
    try:
        children = window.query_tree().children
    except Exception:
        children = []
    descendant_matched = False
    for child in children:
        if _walk_collect_games(child, results):
            descendant_matched = True
    _drop_if_frame(results, own_index, game is not None, descendant_matched)
    return game is not None or descendant_matched


def get_window_root_x(wid: str) -> int | None:
    """Return the window's top-left X coordinate in root-window space.

    This is the value xdotool prints as ``Position:`` and what we use to
    sort toon windows left-to-right.
    """
    d = _open_display()
    if d is None:
        return None
    try:
        win = d.create_resource_object("window", int(wid))
        root = d.screen().root
        coords = root.translate_coords(win, 0, 0)
        return int(coords.x)
    except Exception:
        return None


def get_window_geometry(wid: str) -> tuple[int, int, int, int] | None:
    """(root_x, root_y, width, height) of the client window, root-space.

    Origin via translate_coords against root (same approach as
    get_window_root_x); size via get_geometry. None on any failure.
    The two queries are separate round trips, so a window moved/resized
    between them yields a torn tuple — acceptable: gestures snapshot
    geometry once at press, bounding the blast radius to one gesture."""
    d = _open_display()
    if d is None:
        return None
    try:
        win = d.create_resource_object("window", int(wid))
        root = d.screen().root
        coords = root.translate_coords(win, 0, 0)
        geo = win.get_geometry()
        return (int(coords.x), int(coords.y), int(geo.width), int(geo.height))
    except Exception:
        return None


def toplevel_at_point(root_x: int, root_y: int) -> str | None:
    """The topmost mapped direct child of root containing the point
    (stacking-aware, pointer-independent: works on recorded coordinates).
    Under a reparenting WM this is the frame window; compare it against
    toplevel_ancestor(client_wid).

    Tri-state result: a window id string when a toplevel contains the
    point; "" (empty string) when the lookup SUCCEEDED but no toplevel is
    there (bare root/desktop); None only on lookup FAILURE (no display /
    X error). Callers use the distinction to ignore clean misses while
    falling back on real failures."""
    d = _open_display()
    if d is None:
        return None
    try:
        root = d.screen().root
        res = root.translate_coords(root, int(root_x), int(root_y))
        child = getattr(res, "child", None)
        if child in (None, 0) or getattr(child, "id", 0) == 0:
            return ""  # clean miss: the point is over the bare root
        return str(child.id)
    except Exception:
        return None


def toplevel_ancestor(wid: str) -> str | None:
    """Walk parents until the direct child of root: the WM frame, or the
    window itself when unparented. None on failure."""
    d = _open_display()
    if d is None:
        return None
    try:
        win = d.create_resource_object("window", int(wid))
        root_id = d.screen().root.id
        for _ in range(32):  # parent chains are short; bound the walk
            parent = win.query_tree().parent
            if parent is None or getattr(parent, "id", 0) == 0:
                return None
            if parent.id == root_id:
                return str(win.id)
            win = parent
        return None
    except Exception:
        return None


def get_active_window_id() -> str | None:
    """Read ``_NET_ACTIVE_WINDOW`` from the root window. Returns the active
    window ID as a decimal string, or None on Wayland-only sessions / when
    the property is missing.
    """
    d = _open_display()
    if d is None:
        return None
    try:
        root = d.screen().root
        atom = d.intern_atom("_NET_ACTIVE_WINDOW")
        from Xlib import X  # type: ignore
        prop = root.get_full_property(atom, X.AnyPropertyType)
        if prop and prop.value:
            return str(int(prop.value[0]))
    except Exception:
        return None
    return None


def get_window_pid(wid: str) -> int | None:
    """Read ``_NET_WM_PID`` from the window. Returns the PID as set by the
    window's owner (this is a namespace PID inside a Flatpak game install;
    callers who need the host PID should prefer the XRes path instead).
    """
    d = _open_display()
    if d is None:
        return None
    try:
        win = d.create_resource_object("window", int(wid))
        atom = d.intern_atom("_NET_WM_PID")
        from Xlib import X  # type: ignore
        prop = win.get_full_property(atom, X.AnyPropertyType)
        if prop and prop.value:
            return int(prop.value[0])
    except Exception:
        return None
    return None
