"""Resolve the main window's compositing mode and (later) run the GNOME/Mutter
frame-then-strip bootstrap. See
docs/superpowers/specs/2026-06-21-gnome-frameless-window-bootstrap-design.md.

This module currently holds the pure decision + encoder functions, WM detection,
and settings-cache helpers. The live X sequence (run_frame_then_strip /
show_with_bootstrap) is added in a later task."""
from __future__ import annotations

# Resolved-mode constants
PURE_FRAMELESS = "pure_frameless"
FRAME_THEN_STRIP = "frame_then_strip"
BORDER_ONLY = "border_only"
NATIVE_TITLE_BAR = "native_title_bar"

# Motif decoration field values (MWM_DECOR_*)
DECOR_NONE = 0
DECOR_ALL = 1
DECOR_BORDER = 2

# WMs proven to composite managed frameless XWayland windows natively.
KNOWN_GOOD_WMS = frozenset({"KWin"})

_CACHE_KEY = "window_compositing_cache"


def resolve_window_mode(*, platform, session_type, qpa_platform, wm_name,
                        use_system_title_bar, cached_mode):
    """Pure decision for the main window's compositing mode.

    cached_mode: a previously-resolved runtime fallback for this environment
    signature (or None). Only BORDER_ONLY / NATIVE_TITLE_BAR downgrades are
    honored; the cache never upgrades a bootstrap environment back to pure."""
    if use_system_title_bar:
        return NATIVE_TITLE_BAR
    if platform != "linux":
        return PURE_FRAMELESS
    if session_type != "wayland" or qpa_platform != "xcb":
        return PURE_FRAMELESS
    if wm_name in KNOWN_GOOD_WMS:
        return PURE_FRAMELESS
    if cached_mode in (BORDER_ONLY, NATIVE_TITLE_BAR):
        return cached_mode
    return FRAME_THEN_STRIP


def motif_hints_value(decorations):
    """_MOTIF_WM_HINTS as a 5-CARDINAL list. flags=2 => only the decorations
    field is significant; functions/input_mode/status left 0."""
    return [2, 0, int(decorations), 0, 0]


def environment_signature(*, qpa_platform, session_type, wm_name, qt_version):
    """Stable cache key for the current environment."""
    return f"{qpa_platform}|{session_type}|{wm_name}|{qt_version}"


def detect_wm_name(display):
    """Return the running WM's _NET_WM_NAME (e.g. 'GNOME Shell', 'KWin',
    'Mutter (Muffin)'), or None. Reads _NET_SUPPORTING_WM_CHECK on the root,
    then _NET_WM_NAME on the indicated window. `display` is an Xlib Display
    (or compatible)."""
    try:
        support_atom = display.intern_atom("_NET_SUPPORTING_WM_CHECK")
        name_atom = display.intern_atom("_NET_WM_NAME")
        root = display.screen().root
        prop = root.get_full_property(support_atom, 0)
        if not prop or not prop.value:
            return None
        wid = int(prop.value[0])
        check = display.create_resource_object("window", wid)
        nprop = check.get_full_property(name_atom, 0)
        if not nprop or not nprop.value:
            return None
        raw = nprop.value
        if isinstance(raw, bytes):
            return raw.decode("utf-8", "replace").strip("\x00") or None
        return str(raw).strip("\x00") or None
    except Exception:
        return None


def cached_mode_for(settings, signature):
    """Return the cached resolved mode for this signature, or None."""
    cache = settings.get(_CACHE_KEY, {}) or {}
    return cache.get(signature)


def cache_resolved_mode(settings, signature, mode):
    """Persist the resolved working mode for this signature. Stores a single
    entry (the current environment) to avoid unbounded growth."""
    settings.set(_CACHE_KEY, {signature: mode})
