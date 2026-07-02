"""Resolve the main window's compositing mode and run the GNOME/Mutter
frame-then-strip bootstrap. See
docs/superpowers/specs/2026-06-21-gnome-frameless-window-bootstrap-design.md.

Holds the pure decision + encoder functions, WM detection, settings-cache
helpers, and the live X sequence (run_frame_then_strip / show_with_bootstrap).
Qt/Xlib are imported lazily inside the runner so the module stays import-pure
on platforms without an X server."""
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
    """Stable cache key for the current environment. The '|' separator assumes
    the components contain no pipe; _NET_WM_NAME values are clean identifiers in
    practice. A None wm_name renders as the literal 'None' (stable + distinct)."""
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
    """Replace the cache with a single entry for this signature. Keyed to the
    current environment to prevent unbounded growth across environment changes
    (any prior signature's entry is intentionally dropped).

    NOTE: has no runtime callers by design. The runner's deep-failure fallback
    persists the native title bar via the global use_system_title_bar setting,
    not this cache. This helper exists to pin BORDER_ONLY (or NATIVE_TITLE_BAR)
    for a specific environment via spike/manual settings intervention; that is
    the only way resolve_window_mode's BORDER_ONLY cache branch is reached."""
    settings.set(_CACHE_KEY, {signature: mode})


# Strip timeout from the Task 1 spike (frame-extents appeared at ~10ms; 500ms is safe).
FRAME_EXTENTS_TIMEOUT_MS = 500
WATCHDOG_MS = 1500
_STAGE_OPACITY = 1  # near-invisible; avoids 'exactly 0 optimized away'


def resolve_mode_for_env(settings, env):
    """Resolve the window mode for `env` - the same decision
    show_with_bootstrap makes, side-effect free. `env` is a dict with keys:
    platform, session_type, qpa_platform, wm_name, use_system_title_bar,
    qt_version."""
    sig = environment_signature(
        qpa_platform=env["qpa_platform"], session_type=env["session_type"],
        wm_name=env["wm_name"], qt_version=env["qt_version"])
    return resolve_window_mode(
        platform=env["platform"], session_type=env["session_type"],
        qpa_platform=env["qpa_platform"], wm_name=env["wm_name"],
        use_system_title_bar=env["use_system_title_bar"],
        cached_mode=cached_mode_for(settings, sig))


def show_with_bootstrap(window, *, settings, env, _run_frame_then_strip=None):
    """Resolve the window mode and either show() normally or run the bootstrap.
    `env` is a dict with keys: platform, session_type, qpa_platform, wm_name,
    use_system_title_bar, qt_version. `_run_frame_then_strip` is injectable for
    tests; defaults to the live runner."""
    mode = resolve_mode_for_env(settings, env)

    if mode in (PURE_FRAMELESS, NATIVE_TITLE_BAR):
        window.show()
        return

    runner = _run_frame_then_strip or run_frame_then_strip
    runner(window, settings=settings, border_only=(mode == BORDER_ONLY))


def run_frame_then_strip(window, *, settings, border_only=False):
    """Live frame-then-strip on the realized window. Stages near-invisible,
    forces a server frame, strips it once Mutter creates the frame (keeps the
    border when border_only=True), reasserts geometry, then reveals. On a
    frame-extents timeout, persists the native title bar for the next launch.
    Imports Qt/Xlib lazily so the module stays import-pure off X; any X setup or
    staging error falls back to a plain show() so the app is never left hidden."""
    from PySide6.QtCore import QTimer

    try:
        from Xlib import display as _xd, Xatom
        geom = (window.x(), window.y(), window.width(), window.height())
        d = _xd.Display()
        mwh = d.intern_atom("_MOTIF_WM_HINTS")
        opacity = d.intern_atom("_NET_WM_WINDOW_OPACITY")
        fe = d.intern_atom("_NET_FRAME_EXTENTS")
        xid = int(window.winId())
    except Exception:
        window.show()
        return

    def _set_motif(dec):
        w = d.create_resource_object("window", xid)
        w.change_property(mwh, mwh, 32, motif_hints_value(dec))
        d.sync()

    def _set_opacity(val):
        w = d.create_resource_object("window", xid)
        w.change_property(opacity, Xatom.CARDINAL, 32, [val])
        d.sync()

    def _reveal():
        # Prefer deleting the opacity property (fully opaque); if that fails,
        # set 0xFFFFFFFF so the window can never be left staged-invisible.
        w = d.create_resource_object("window", xid)
        try:
            w.delete_property(opacity)
        except Exception:
            w.change_property(opacity, Xatom.CARDINAL, 32, [0xFFFFFFFF])
        d.sync()

    def _frame_extents():
        w = d.create_resource_object("window", xid)
        p = w.get_full_property(fe, 0)
        return list(p.value) if p else None

    def _close():
        try:
            d.close()
        except Exception:
            pass

    try:
        _set_opacity(_STAGE_OPACITY)
        _set_motif(DECOR_BORDER if border_only else DECOR_ALL)
    except Exception:
        try:
            _reveal()
        except Exception:
            pass
        _close()
        window.show()
        return
    window.show()

    done = {"v": False}

    def _finish_strip():
        if done["v"]:
            return
        done["v"] = True
        if not border_only:
            _set_motif(DECOR_NONE)
        window.setGeometry(*geom)
        _reveal()
        _close()

    elapsed = {"t": 0}

    def _poll():
        if done["v"]:
            return
        elapsed["t"] += 10
        ext = _frame_extents()
        if ext and any(ext):
            _finish_strip()
            return
        if elapsed["t"] >= FRAME_EXTENTS_TIMEOUT_MS:
            # Decorated frame never appeared (deep failure). border_only needs
            # the SAME frame, so escalate straight to the native title bar for
            # the NEXT launch (via the existing setting) and reveal as-is now.
            done["v"] = True
            settings.set("use_system_title_bar", True)
            _reveal()
            _close()
            return
        QTimer.singleShot(10, _poll)

    def _watchdog():
        if done["v"]:
            return
        done["v"] = True
        _reveal()
        _close()
    QTimer.singleShot(WATCHDOG_MS, _watchdog)
    QTimer.singleShot(10, _poll)
