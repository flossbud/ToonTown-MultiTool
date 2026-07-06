"""macOS overlay backend: NSWindow levels + the shared cursor-region arbiter.

The X11 backend punches input-only holes with the X Shape extension; macOS has
no input-shape API. Every mechanism below was probed live on the Mac (ledger:
docs/superpowers/specs/2026-07-03-macos-overlay-probe-ledger.md):

- ``NSWindow.setIgnoresMouseEvents_`` makes a whole window click-through and
  flips at runtime in ~0.2 ms (CP2: zero leaked clicks across fast boundary
  crossings at a 60 Hz poll; wheel events reach a hovered, never-activated
  overlay window).
- Clicking an interactive region of a plain ``NSWindow`` ACTIVATES the app
  (the game loses key). An ``NSPanel`` with
  ``NSWindowStyleMaskNonactivatingPanel`` takes clicks with ZERO activations
  (CP2-C: 58/58), so overlay surfaces are realized as panels on cocoa
  (``Qt.Tool``; see OverlaySurface) and this backend applies the mask pre-map.
- Distinct NSWindow LEVELS beat raise order (CP4), so the
  radial/panel-above-cluster invariant is levels: cluster at the floating
  level (3), radial/panel one above (4). Hardened windows stay above the
  frontmost, clicked game. Qt's own StaysOnTop level (8) is overridden.
- ``QWidget.setWindowOpacity`` blanks/restores exactly (CP3), so the content
  blanking / paint-staging machinery keeps its semantics unchanged.
- Fresh resize regions composite TRANSPARENT under a stalled event loop
  (CP6): the KWin black-band physics do not exist here; blanking is
  belt-and-suspenders.
- Background 16 ms timers are NOT App-Nap throttled (CP5: 62.5 Hz held), so
  the lazy arbiter poll needs no activity assertions.

Coordinate contract (differs from Windows, on purpose): macOS emits LOGICAL
points and Qt globals are logical, so ``apply_input_shape`` polygonizes at
dpr=1.0 and the arbiter ports (QCursor.pos / widget mapToGlobal) are logical
too - one consistent space, DPR-independent by construction (the identity law,
utils/screen_coords.py).

OWNERSHIP RULE: the arbiter is the ONLY writer of ``ignoresMouseEvents`` on
arbitrated surfaces (its applied-state cache is what makes flips cheap). The
level/behavior hardening here never touches that bit, and the post-map
re-asserts call ``arbiter.invalidate`` so a recreated native window (cocoa
PlatformSurface) cannot strand a stale cached state.

All PyObjC imports are lazy and every NSWindow touch is gated on the REAL
cocoa QPA via ``is_available()`` - never ``sys.platform`` alone (the
winId->objc offscreen segfault class). The constructor is pure (no winId, no
PyObjC) so the factory and tests can construct this class anywhere.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

from utils.overlay.backend import OverlayBackend, overlay_trace
from utils.overlay.cursor_arbiter import ARBITER_INTERVAL_MS, CursorRegionArbiter

# NSWindow levels, kept literal so pure tests run anywhere (CP1 readbacks:
# normal=0, floating=3, Qt StaysOnTop=8, status=25 on macOS 26.5).
CLUSTER_WINDOW_LEVEL = 3   # kCGFloatingWindowLevel
PANEL_WINDOW_LEVEL = 4     # floating+1: radial/panel strictly above (CP4)
GHOST_WINDOW_LEVEL = 5     # panel+1: glove cursor mirrors draw above EVERY
                           # overlay surface (a ghost press can activate radial
                           # spokes, so the glove must be visible over the ring)

# collectionBehavior bits: canJoinAllSpaces | stationary (the proven ghost
# recipe, utils/macos_overlay.py; CP1 confirmed it sticks on plain Qt windows).
_COLLECTION_BEHAVIOR = (1 << 0) | (1 << 4)

# NSWindowStyleMaskNonactivatingPanel - NSPanel-only (CP2-C).
_NONACTIVATING_PANEL_MASK = 1 << 7

# Runtime QNSPanel subclass whose constrainFrameRect:toScreen: is a
# pass-through. AppKit clamps EVERY frame set (Qt setGeometry, NSWindow
# setFrame/setFrameOrigin all probed CLAMPED, CP10) to the visible screen
# area, so the oversized cluster envelope walls against the menu bar while
# the controller model keeps moving - a 220 px model/window divergence that
# displaced the input region and froze the whole float UI live. The subclass
# inherits every Qt override (it derives from QNSPanel itself, never plain
# NSPanel) and is applied per-instance via libobjc object_setClass (CP10b:
# qt-thinks == actual == requested at negative Y after the swizzle). This is
# the cocoa analog of the X11 DOCK-type clamp exemption (see
# OverlaySurface.WM_WINDOW_TYPE).
_FREE_PANEL_CLASS_NAME = "TTMTConstrainFreePanel"

# Keep the method's Python callable + libobjc handle alive for the process
# lifetime (PyObjC holds its own ref through the registration; the module
# ref is cheap insurance).
_LIBOBJC = None
_FREE_PANEL_METHOD = None
_FREE_PANEL_CLS = 0

# Chord-capture keyboard sessions (the Spotlight pattern): a nonactivating
# panel IS allowed to become the key window without activating its app -
# that is how Spotlight/Alfred take typing while the previous app stays
# frontmost. Qt's WindowDoesNotAcceptFocus pins QNSPanel's
# canBecomeKeyWindow to NO, so no keyboard event is EVER delivered to an
# overlay surface (live: the Settings chord-capture button was deaf, every
# key beeped off the still-key app, 2026-07-05). The runtime subclass
# overrides canBecomeKeyWindow to consult this membership set: a window is
# key-capable exactly while a capture session holds it open, and the
# override returns NO otherwise - identical to Qt's own answer for every
# overlay surface (they all carry WindowDoesNotAcceptFocus).
# Keyed by objc pointer (objc.pyobjc_id); entries live only for the span
# of one capture session, so pointer reuse cannot alias.
_KEY_SESSION_WINDOWS: set[int] = set()
_KEY_METHOD_OK = False
_KEY_METHOD_CB = None  # keep the Python callable alive (same rule as above)


def _objc_ptr(win) -> int:
    """Stable identity for an NSWindow proxy (the raw objc pointer). The
    canBecomeKeyWindow override and the session set must agree on this
    token; tests monkeypatch it to id()."""
    import objc
    return objc.pyobjc_id(win)


# The window-level override is only HALF the delivery path: AppKit routes a
# key window's keyDown to its FIRST RESPONDER, and Qt's QNSView refuses
# first-responder status for WindowDoesNotAcceptFocus windows (the same flag
# consult, one layer down). Probed live 2026-07-05: the panel became key
# (BEGIN key=True), the tap passed every keystroke, and the events still
# died unhandled at the NSWindow (system beep) - so the content view gets
# the same runtime-subclass treatment, gated on the same session set.
_KEY_VIEW_CLASS_NAME = "TTMTKeySessionView"
_KEY_VIEW_CLS = 0
_KEY_VIEW_BASE = None   # runtime class name the subclass was built on
_KEY_VIEW_CB = None     # keep the Python callable alive


def _ensure_key_view_class(lib, base_name: bytes) -> int:
    """Register the acceptsFirstResponder-override subclass of the content
    view's own runtime class. One registration per process; if a later view
    reports a DIFFERENT base class the swizzle is refused (never subclass a
    layout we did not verify)."""
    global _KEY_VIEW_CLS, _KEY_VIEW_BASE, _KEY_VIEW_CB
    if _KEY_VIEW_CLS:
        return _KEY_VIEW_CLS if base_name == _KEY_VIEW_BASE else 0
    try:
        import objc
        existing = lib.objc_getClass(_KEY_VIEW_CLASS_NAME.encode())
        if not existing:
            base = lib.objc_getClass(base_name)
            if not base:
                return 0
            cls = lib.objc_allocateClassPair(
                base, _KEY_VIEW_CLASS_NAME.encode(), 0)
            if not cls:
                return 0
            lib.objc_registerClassPair(cls)
            existing = cls

        def acceptsFirstResponder(self):
            try:
                w = self.window()
                return w is not None and _objc_ptr(w) in _KEY_SESSION_WINDOWS
            except Exception:
                return False

        sel = lib.sel_registerName(b"acceptsFirstResponder")
        method = lib.class_getInstanceMethod(lib.objc_getClass(base_name), sel)
        encoding = lib.method_getTypeEncoding(method) if method else None
        target = objc.lookUpClass(_KEY_VIEW_CLASS_NAME)
        for enc in (encoding, b"B@:", b"c@:"):
            if enc is None:
                continue
            try:
                objc.classAddMethods(target, [objc.selector(
                    acceptsFirstResponder,
                    selector=b"acceptsFirstResponder",
                    signature=enc)])
                _KEY_VIEW_CB = acceptsFirstResponder
                _KEY_VIEW_CLS = existing
                _KEY_VIEW_BASE = base_name
                overlay_trace("macos key-session: view responder class registered "
                              f"(base={base_name.decode()})")
                return existing
            except Exception:
                continue
        return 0
    except Exception:
        return 0


def _libobjc():
    """libobjc with the runtime functions typed. Cached; None on failure."""
    global _LIBOBJC
    if _LIBOBJC is not None:
        return _LIBOBJC
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("objc"))
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.objc_allocateClassPair.restype = ctypes.c_void_p
        lib.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.c_size_t]
        lib.objc_registerClassPair.restype = None
        lib.objc_registerClassPair.argtypes = [ctypes.c_void_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        lib.class_getInstanceMethod.restype = ctypes.c_void_p
        lib.class_getInstanceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.method_getTypeEncoding.restype = ctypes.c_char_p
        lib.method_getTypeEncoding.argtypes = [ctypes.c_void_p]
        lib.class_addMethod.restype = ctypes.c_bool
        lib.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_char_p]
        lib.object_setClass.restype = ctypes.c_void_p
        lib.object_setClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.object_getClassName.restype = ctypes.c_char_p
        lib.object_getClassName.argtypes = [ctypes.c_void_p]
        _LIBOBJC = lib
        return lib
    except Exception:
        return None


def _ensure_free_panel_class(lib) -> int:
    """Register the runtime subclass once; returns the Class pointer (or 0).

    Two-step, each step chosen by a failed alternative:
    1. The CLASS is registered bare through libobjc (objc_allocateClassPair,
       zero ivars) so swizzled instances keep QNSPanel's memory layout -
       a PyObjC-defined class adds a Python-state ivar and crashed live
       (SIGSEGV in object_getattro, faulthandler 2026-07-03).
    2. The METHOD is bridged onto it by PyObjC classAddMethods (the category
       mechanism - touches no instance layout) because a raw ctypes IMP
       cannot return NSRect: ctypes callbacks reject struct result types
       ("invalid result type for callback function", probed CP10c)."""
    global _FREE_PANEL_METHOD, _FREE_PANEL_CLS
    if _FREE_PANEL_CLS:
        return _FREE_PANEL_CLS
    try:
        import objc
        existing = lib.objc_getClass(_FREE_PANEL_CLASS_NAME.encode())
        if not existing:
            base = lib.objc_getClass(b"QNSPanel")
            if not base:
                return 0
            cls = lib.objc_allocateClassPair(
                base, _FREE_PANEL_CLASS_NAME.encode(), 0)
            if not cls:
                return 0
            lib.objc_registerClassPair(cls)
            existing = cls
        # Method encoding copied from QNSPanel's own implementation, with a
        # clean-literal fallback (runtime encodings can carry offsets some
        # PyObjC versions reject).
        sel = lib.sel_registerName(b"constrainFrameRect:toScreen:")
        method = lib.class_getInstanceMethod(
            lib.objc_getClass(b"QNSPanel"), sel)
        encoding = lib.method_getTypeEncoding(method) if method else None
        rect_t = b"{CGRect={CGPoint=dd}{CGSize=dd}}"
        fallback = rect_t + b"@:" + rect_t + b"@"

        def constrainFrameRect_toScreen_(self, rect, screen):
            return rect

        target = objc.lookUpClass(_FREE_PANEL_CLASS_NAME)
        added = False
        for enc in (encoding, fallback):
            if enc is None:
                continue
            try:
                objc.classAddMethods(target, [objc.selector(
                    constrainFrameRect_toScreen_,
                    selector=b"constrainFrameRect:toScreen:",
                    signature=enc)])
                added = True
                break
            except Exception:
                continue
        if not added:
            return 0
        _FREE_PANEL_METHOD = constrainFrameRect_toScreen_
        _add_key_window_method(lib, target)
        _FREE_PANEL_CLS = existing
        overlay_trace("macos constrain-exempt: runtime class registered")
        return existing
    except Exception:
        return 0


def _add_key_window_method(lib, target) -> None:
    """Bridge canBecomeKeyWindow onto the runtime class (same category
    mechanism as constrainFrameRect - never a PyObjC subclass, CP10).

    A failure here is deliberately non-fatal: the constrain exemption is
    load-bearing for the whole float UI, key sessions only for chord
    capture, so the class must register even if this method cannot. A
    begin_key_session against a class without the override simply finds
    isKeyWindow False (makeKeyWindow consults canBecomeKeyWindow) and
    reports the session as not established."""
    global _KEY_METHOD_OK, _KEY_METHOD_CB
    try:
        import objc

        def canBecomeKeyWindow(self):
            try:
                return _objc_ptr(self) in _KEY_SESSION_WINDOWS
            except Exception:
                return False

        sel = lib.sel_registerName(b"canBecomeKeyWindow")
        method = lib.class_getInstanceMethod(lib.objc_getClass(b"QNSPanel"), sel)
        encoding = lib.method_getTypeEncoding(method) if method else None
        # BOOL encodes as 'B' (arm64) or 'c' (x86_64); try the runtime's own
        # encoding first, then both literals (universal2).
        for enc in (encoding, b"B@:", b"c@:"):
            if enc is None:
                continue
            try:
                objc.classAddMethods(target, [objc.selector(
                    canBecomeKeyWindow,
                    selector=b"canBecomeKeyWindow",
                    signature=enc)])
                _KEY_METHOD_CB = canBecomeKeyWindow
                _KEY_METHOD_OK = True
                overlay_trace("macos key-session: canBecomeKeyWindow bridged")
                return
            except Exception:
                continue
        overlay_trace("macos key-session: canBecomeKeyWindow bridge FAILED "
                      "(chord capture will stay deaf on overlay surfaces)")
    except Exception:
        pass


class MacOSOverlayBackend(OverlayBackend):
    """OverlayBackend for macOS: NSWindow hardening + the cursor arbiter."""

    def __init__(self) -> None:
        self._arbiter = CursorRegionArbiter(
            cursor_pos=self._get_cursor_pos,
            window_origin=self._get_window_origin,
            apply_transparent=self._set_ignores_mouse,
        )
        self._timer = None  # lazy QTimer, GUI thread, runs only while needed
        self._pyobjc_ok: bool | None = None  # lazy import check, cached
        if self.is_available():
            overlay_trace("MacOSOverlayBackend: available (cursor arbiter ready)")

    # -- availability ----------------------------------------------------

    def is_available(self) -> bool:
        """darwin + the REAL cocoa QPA + PyObjC importable.

        The platformName gate (not sys.platform) is load-bearing: under the
        offscreen QPA winId() is not an NSView and wrapping it segfaults
        natively, so every gate downstream of is_available() must stay off.
        """
        if sys.platform != "darwin":
            return False
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app is None or QGuiApplication.platformName() != "cocoa":
                return False
        except Exception:
            return False
        if self._pyobjc_ok is None:
            try:
                import objc  # noqa: F401
                import AppKit  # noqa: F401
                self._pyobjc_ok = True
            except Exception:
                self._pyobjc_ok = False
        return self._pyobjc_ok

    def wants_taskbar_rep(self) -> bool:
        """The aligned-mirror representative is a KWin workaround. On macOS the
        APP owns its Dock icon and Cmd-Tab entry regardless of window state -
        per-window identity work does not exist here. (The controller stamps
        WIN_TASKBAR_IDENTITY when this returns False; that attr is win32
        ex-style data and is deliberately ignored by this backend, while its
        generic surface behaviors - spontaneous close -> app quit, minimize
        bounce - are sensible on cocoa too.)"""
        return False

    # -- NSWindow access (fresh resolve per call, never cached) -----------

    def _nswindow(self, window):
        """Resolve the widget's NSWindow fresh from winId(); None on failure.

        Only ever called behind is_available() (cocoa QPA), matching the
        proven macos_overlay recipe: never cache a wrapped objc ref across
        native surface recreation."""
        try:
            import objc
            view = objc.objc_object(c_void_p=int(window.winId()))
            return view.window()
        except Exception:
            return None

    # -- OS ports (injected into the arbiter; thin, no logic) ------------

    @staticmethod
    def _get_cursor_pos():
        """Logical global cursor point (matches the dpr=1.0 regions)."""
        try:
            from PySide6.QtGui import QCursor
            pos = QCursor.pos()
            return pos.x(), pos.y()
        except Exception:
            return None

    @staticmethod
    def _get_window_origin(key):
        """Logical global origin of the surface's client area; None evicts.

        The key IS the surface widget (opaque to the arbiter). A destroyed
        C++ object raises RuntimeError -> evict; a live but handle-less
        widget cannot receive input anyway -> evict (re-registered on the
        next apply_input_region)."""
        try:
            if key.windowHandle() is None:
                return None
            from PySide6.QtCore import QPoint
            p = key.mapToGlobal(QPoint(0, 0))
            return p.x(), p.y()
        except Exception:
            return None

    def _set_ignores_mouse(self, key, transparent: bool) -> None:
        win = self._nswindow(key)
        if win is None:
            return
        win.setIgnoresMouseEvents_(bool(transparent))

    # -- window hints -----------------------------------------------------

    def set_overlay_hints(self, window) -> None:
        return  # flags are set on the Qt side, matching the other backends

    def set_initial_state(self, window) -> None:
        """Pre-map NSWindow hardening: level per surface role + all-Spaces
        behavior + the nonactivating panel mask.

        Called while the native handle exists but the window is unmapped
        (prepare_initial_state), so the first mapped frame is already at the
        right level with no activation window. NEVER touches
        ignoresMouseEvents (arbiter ownership rule)."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        level = self._level_for(window)
        try:
            win.setLevel_(level)
            win.setCollectionBehavior_(_COLLECTION_BEHAVIOR)
        except Exception:
            return
        panel = self._apply_nonactivating(win)
        free = self._exempt_frame_constrain(win)
        self._disable_window_shadow(win)
        overlay_trace(
            f"macos set_initial_state: pre-map level={level} "
            f"behavior=allSpaces|stationary "
            f"{'nonactivating-panel' if panel else 'NOT a panel (activation possible)'} "
            f"constrain-free={free} shadow=off")

    @staticmethod
    def _level_for(window) -> int:
        """Surface role -> NSWindow level, keyed off the same WM_WINDOW_TYPE
        class attr the X11 backend reads (DOCK = cluster; the radial/panel
        subclasses override it with the OSD type). Levels enforce the
        radial/panel-above-cluster invariant immune to raise order (CP4)."""
        wtype = getattr(window, "WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK")
        if wtype == "_NET_WM_WINDOW_TYPE_DOCK":
            return CLUSTER_WINDOW_LEVEL
        return PANEL_WINDOW_LEVEL

    def _apply_nonactivating(self, win) -> bool:
        """styleMask |= NonactivatingPanel + never hide on app deactivate.
        NSPanel-only; returns whether the window is a panel."""
        try:
            import AppKit
            if not win.isKindOfClass_(AppKit.NSPanel):
                return False
            win.setStyleMask_(win.styleMask() | _NONACTIVATING_PANEL_MASK)
            win.setHidesOnDeactivate_(False)
            return True
        except Exception:
            return False

    @staticmethod
    def _disable_window_shadow(win) -> None:
        """AppKit's own drop shadow traces the translucent content's alpha
        silhouette as a thin choppy dark outline around the painted glow
        (live finding, first float entry). The surfaces paint their own
        glow/shadow; the native one is pure artifact."""
        try:
            win.setHasShadow_(False)
        except Exception:
            pass

    def _exempt_frame_constrain(self, win) -> bool:
        """isa-swizzle *win* onto the constrain-free QNSPanel subclass.

        The subclass is registered at the PURE ObjC-runtime level
        (objc_allocateClassPair, ZERO added ivars, ctypes IMP) so the
        swizzled instance's memory layout is identical to QNSPanel - the
        KVO pattern. DISPROVEN alternative (crashed live, faulthandler
        2026-07-03): a PyObjC-defined subclass - PyObjC classes add a
        Python-state ivar their already-allocated instances don't have, so
        the first attribute access through the proxy dereferences garbage
        (SIGSEGV in object_getattro). Never define the subclass in PyObjC.

        Idempotent; QNSPanel-only by exact class-name match; all
        verification goes through libobjc (never the PyObjC proxy) once the
        isa has changed. Never raises."""
        try:
            import objc
            lib = _libobjc()
            if lib is None:
                return False
            win_ptr = objc.pyobjc_id(win)
            name = lib.object_getClassName(win_ptr)
            if name == _FREE_PANEL_CLASS_NAME.encode():
                return True
            if name != b"QNSPanel":
                overlay_trace(f"macos constrain-exempt skipped: class={name!r}")
                return False
            cls_ptr = _ensure_free_panel_class(lib)
            if not cls_ptr:
                return False
            lib.object_setClass(win_ptr, cls_ptr)
            return lib.object_getClassName(win_ptr) == _FREE_PANEL_CLASS_NAME.encode()
        except Exception:
            return False

    def set_above(self, window) -> None:
        """Re-assert level+behavior per show (parity with the EWMH re-send).

        Also invalidates the arbiter's cached click-through state for this
        surface: a hide/show cycle can recreate the native NSWindow with the
        default (interactive) bit while the cache still holds the old state,
        and the cache-first apply would never correct it."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        try:
            win.setLevel_(self._level_for(window))
            win.setCollectionBehavior_(_COLLECTION_BEHAVIOR)
        except Exception:
            pass
        # A recreated native window is a fresh (clamping, shadowed) QNSPanel:
        # re-assert the exemption and shadow-off beside the level.
        self._exempt_frame_constrain(win)
        self._disable_window_shadow(win)
        self._arbiter.invalidate(window)

    def set_non_activating(self, window) -> None:
        """Re-assert the nonactivating panel bits (idempotent, per show)."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        self._apply_nonactivating(win)

    def set_rep_initial_state(self, window) -> None:
        """No-op: the representative is never constructed on macOS
        (wants_taskbar_rep() is False; the Dock identity is app-level)."""
        overlay_trace("macos set_rep_initial_state: no-op (rep unused on macOS)")

    # -- chord-capture keyboard session ------------------------------------

    def begin_key_session(self, window) -> bool:
        """Let *window* (an overlay surface) receive keyboard events for the
        span of a chord capture, WITHOUT activating the app - the Spotlight
        pattern. Returns whether the window actually became key (the caller
        treats False as "capture stays deaf", never an error)."""
        if not self.is_available():
            return False
        win = self._nswindow(window)
        if win is None:
            return False
        # The override lives on the runtime subclass; make sure this window
        # is swizzled (idempotent - surfaces already are, pre-map).
        if not self._exempt_frame_constrain(win) or not _KEY_METHOD_OK:
            overlay_trace("macos key-session BEGIN refused: "
                          f"swizzle/method unavailable (method_ok={_KEY_METHOD_OK})")
            return False
        try:
            # BOTH halves of the delivery path must open: the WINDOW must be
            # allowed to become key AND its content VIEW must accept first
            # responder, or AppKit drops the keyDown at the window (beep).
            view = win.contentView()
            view_ok = self._exempt_view_responder(view)
            _KEY_SESSION_WINDOWS.add(_objc_ptr(win))
            win.makeKeyWindow()
            if view_ok:
                # After membership: makeFirstResponder consults
                # acceptsFirstResponder, which reads the session set.
                win.makeFirstResponder_(view)
            ok = bool(win.isKeyWindow()) and view_ok
        except Exception:
            ok = False
        overlay_trace(f"macos key-session BEGIN key={ok}")
        return ok

    def _exempt_view_responder(self, view) -> bool:
        """isa-swizzle the content view onto the responder-override subclass
        (mirrors _exempt_frame_constrain; idempotent; never raises)."""
        try:
            import objc
            lib = _libobjc()
            if lib is None or view is None:
                return False
            view_ptr = objc.pyobjc_id(view)
            name = lib.object_getClassName(view_ptr)
            if name == _KEY_VIEW_CLASS_NAME.encode():
                return True
            cls_ptr = _ensure_key_view_class(lib, name)
            if not cls_ptr:
                overlay_trace(f"macos key-session: view swizzle refused (class={name!r})")
                return False
            lib.object_setClass(view_ptr, cls_ptr)
            return lib.object_getClassName(view_ptr) == _KEY_VIEW_CLASS_NAME.encode()
        except Exception:
            return False

    def end_key_session(self, window) -> None:
        """Close the capture session: drop key-capability and hand keyboard
        focus back to the app the user was in. AppKit has no 'resign key'
        command - the reliable primitive is hiding the key window (key falls
        back to the active app) and re-fronting ours without key. Both calls
        run in one event-loop turn, so the panel does not visibly blink."""
        if not self.is_available():
            return
        win = self._nswindow(window)
        if win is None:
            return
        try:
            _KEY_SESSION_WINDOWS.discard(_objc_ptr(win))
            if win.isKeyWindow():
                win.orderOut_(None)
                win.orderFrontRegardless()
        except Exception:
            pass
        overlay_trace("macos key-session END")

    def set_skip_close_animation(self, window) -> None:
        return  # no KWin close animation to skip

    def set_window_opacity(self, window, opacity: float) -> None:
        """Whole-window opacity via Qt (NSWindow alphaValue underneath).

        Probe CP3: pre-map setWindowOpacity(0) keeps the mapped window fully
        invisible and 1.0 restores it pixel-identically, so the content
        blanking / paint-staging machinery keeps its semantics on macOS."""
        try:
            window.setWindowOpacity(max(0.0, min(1.0, float(opacity))))
        except Exception:
            pass

    # -- input shape (the actual macOS work) ------------------------------

    def apply_input_shape(self, window, path, dpr: float) -> None:
        """Logical-coord QPainterPath -> LOGICAL region -> arbiter entry.

        Deliberately ignores the caller's dpr: on macOS the arbiter ports
        (QCursor.pos / mapToGlobal) are logical points, so the region must be
        polygonized at 1.0 to share their space (the identity law; CP2 ran
        this exact contract live). The caller keeps passing the real dpr -
        the X11/win32 backends need it - and this backend owns the divergence."""
        if not self.is_available():
            return
        from utils.overlay.region import device_input_region
        self.apply_input_region(window, device_input_region(path, 1.0))

    def apply_input_region(self, window, region) -> None:
        if not self.is_available() or region is None:
            return
        try:
            window.winId()  # no-op if realized; the port needs a live handle
        except Exception:
            return
        self._arbiter.set_region(window, region)
        self._update_timer()

    def clear_input_region(self, window) -> None:
        if not self.is_available():
            return
        self._arbiter.clear(window)
        self._update_timer()

    # -- arbiter timer -----------------------------------------------------

    def _update_timer(self) -> None:
        """Run the 60 Hz poll only while some region actually needs it."""
        need = self._arbiter.needs_polling
        if need and self._timer is None:
            from PySide6.QtCore import QTimer
            t = QTimer()
            t.setInterval(ARBITER_INTERVAL_MS)
            t.timeout.connect(self._on_tick)
            t.start()
            self._timer = t
            overlay_trace("macos arbiter: 60 Hz cursor poll STARTED")
        elif not need and self._timer is not None:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None
            overlay_trace("macos arbiter: cursor poll stopped (no dynamic regions)")

    def _on_tick(self) -> None:
        self._arbiter.tick()
        # Entries can self-evict on a dead window; stop polling when drained.
        if not self._arbiter.needs_polling:
            self._update_timer()
