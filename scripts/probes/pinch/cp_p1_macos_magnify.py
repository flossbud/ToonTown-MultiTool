"""CP-P1 probe (pinch zoom): is a trackpad pinch (NSEvent magnify) delivered
to a nonactivating panel while its app is INACTIVE - and via which receiver?

The float overlay's surfaces are Qt.Tool windows realized as QNSPanel on
cocoa, hardened with NSWindowStyleMaskNonactivatingPanel (clicks with zero
activations, CP2-C). Wheel events reach a hovered, never-activated overlay
window (CP2); whether MAGNIFY gestures do is unproven. This probe maps a
panel with that identity and installs two independent receivers:

- RECEIVER A: an NSEvent local monitor on the magnify mask. App-local but
  responder-independent - it sees the event even if no responder handles it.
  Returns every event unchanged (never swallows).
- RECEIVER B: magnifyWithEvent:/scrollWheel: overrides on the panel itself,
  installed by isa-swizzling the instance onto a runtime-registered subclass
  of its OWN class (the constrain-exempt pattern from
  utils/overlay/macos_backend.py: bare libobjc class pair with zero ivars so
  the instance layout is untouched, methods bridged via PyObjC
  classAddMethods). scrollWheel: doubles as evidence for scroll delivery.

Run ON THE REAL cocoa SESSION from the repo root (never offscreen - off
cocoa, winId() is not an NSView and wrapping it crashes natively):

    ./venv/bin/python scripts/probes/pinch/cp_p1_macos_magnify.py

No env flags needed. Follow the printed operator steps and record which
receiver lines appear inactive vs active.
"""
import ctypes
import ctypes.util
import platform
import signal
import sys

from PySide6 import QtCore
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

# NSWindowStyleMaskNonactivatingPanel - NSPanel-only (macos_backend recipe).
_NONACTIVATING_PANEL_MASK = 1 << 7

# NSEventTypeMagnify == 30; an NSEventMask bit is 1 << type.
_NSEVENT_MASK_MAGNIFY = 1 << 30

_PROBE_PANEL_CLASS_NAME = "CPP1MagnifyProbePanel"

# NSEventPhase values (a bitmask; gesture events carry one bit or 0).
_PHASE_NAMES = {
    0: "None",
    1: "Began",
    2: "Stationary",
    4: "Changed",
    8: "Ended",
    16: "Cancelled",
    32: "MayBegin",
}

# Keep bridged Python callables, super-IMP trampolines and the monitor token
# alive for the process lifetime (PyObjC/ctypes hold no refs on our behalf).
_LIBOBJC = None
_PROBE_CLS = 0
_METHOD_CBS = []
_SUPER_IMPS = {}
_MONITOR = None
_MONITOR_CB = None


def _phase_name(value) -> str:
    v = int(value)
    return _PHASE_NAMES.get(v, str(v))


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
        lib.method_getImplementation.restype = ctypes.c_void_p
        lib.method_getImplementation.argtypes = [ctypes.c_void_p]
        lib.object_setClass.restype = ctypes.c_void_p
        lib.object_setClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.object_getClassName.restype = ctypes.c_char_p
        lib.object_getClassName.argtypes = [ctypes.c_void_p]
        _LIBOBJC = lib
        return lib
    except Exception:
        return None


def _nswindow(widget):
    """Resolve the widget's NSWindow fresh from winId(); None on failure.
    Only ever called behind the cocoa QPA gate (winId is not an NSView on
    other platforms and wrapping it crashes natively)."""
    try:
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        return view.window()
    except Exception:
        return None


def _apply_nonactivating(win) -> bool:
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


def _capture_super(lib, base_ptr, sel_name: bytes) -> None:
    """Trampoline for the base class's IMP so the overrides can chain to the
    inherited implementation. Both selectors return void and take one object
    arg, so a ctypes call is legal (struct returns are the only IMPs ctypes
    cannot express)."""
    sel = lib.sel_registerName(sel_name)
    method = lib.class_getInstanceMethod(base_ptr, sel)
    fn = None
    if method:
        imp = lib.method_getImplementation(method)
        if imp:
            fn = ctypes.CFUNCTYPE(
                None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(imp)
    _SUPER_IMPS[sel_name] = (fn, sel)


def _call_super(sel_name: bytes, self_obj, event) -> None:
    entry = _SUPER_IMPS.get(sel_name)
    if not entry or entry[0] is None:
        return
    try:
        import objc
        fn, sel = entry
        fn(objc.pyobjc_id(self_obj), sel, objc.pyobjc_id(event))
    except Exception:
        pass


def _monitor_handler(event):
    try:
        print(f"[monitor] phase={_phase_name(event.phase())} "
              f"mag={float(event.magnification()):+.4f} "
              f"winNum={int(event.windowNumber())} "
              f"type={int(event.type())}", flush=True)
    except Exception as exc:
        print(f"[monitor] print failed: {exc}", flush=True)
    return event  # returning None would swallow the event app-wide


def _install_monitor() -> bool:
    """RECEIVER A: NSEvent local monitor on the magnify mask."""
    global _MONITOR, _MONITOR_CB
    try:
        from AppKit import NSEvent
        _MONITOR_CB = _monitor_handler
        _MONITOR = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            _NSEVENT_MASK_MAGNIFY, _monitor_handler)
        return _MONITOR is not None
    except Exception:
        return False


def _remove_monitor() -> None:
    global _MONITOR
    if _MONITOR is None:
        return
    try:
        from AppKit import NSEvent
        NSEvent.removeMonitor_(_MONITOR)
    except Exception:
        pass
    _MONITOR = None


def _ensure_probe_class(lib, base_name: bytes) -> int:
    """Register the probe subclass of *base_name* once; Class pointer or 0.

    Two-step, per the macos_backend constrain-exempt recipe:
    1. The CLASS is registered bare through libobjc (objc_allocateClassPair,
       zero ivars) so swizzled instances keep the base's memory layout - a
       PyObjC-defined class adds a Python-state ivar its already-allocated
       instances don't have (SIGSEGV in object_getattro).
    2. The METHODS are bridged onto it by PyObjC classAddMethods (the
       category mechanism - touches no instance layout), encoding copied
       from the base's own implementation with a clean-literal fallback."""
    global _PROBE_CLS
    if _PROBE_CLS:
        return _PROBE_CLS
    try:
        import objc
        existing = lib.objc_getClass(_PROBE_PANEL_CLASS_NAME.encode())
        if not existing:
            base = lib.objc_getClass(base_name)
            if not base:
                return 0
            cls = lib.objc_allocateClassPair(
                base, _PROBE_PANEL_CLASS_NAME.encode(), 0)
            if not cls:
                return 0
            lib.objc_registerClassPair(cls)
            existing = cls

        base_ptr = lib.objc_getClass(base_name)
        _capture_super(lib, base_ptr, b"magnifyWithEvent:")
        _capture_super(lib, base_ptr, b"scrollWheel:")

        def magnifyWithEvent_(self, event):
            try:
                print(f"[responder] phase={_phase_name(event.phase())} "
                      f"mag={float(event.magnification()):+.4f}", flush=True)
            except Exception as exc:
                print(f"[responder] print failed: {exc}", flush=True)
            _call_super(b"magnifyWithEvent:", self, event)

        def scrollWheel_(self, event):
            try:
                print(f"[responder-scroll] phase={_phase_name(event.phase())} "
                      f"momentum={_phase_name(event.momentumPhase())} "
                      f"dy={float(event.scrollingDeltaY()):+.2f}", flush=True)
            except Exception as exc:
                print(f"[responder-scroll] print failed: {exc}", flush=True)
            _call_super(b"scrollWheel:", self, event)

        target = objc.lookUpClass(_PROBE_PANEL_CLASS_NAME)
        for sel_name, fn in ((b"magnifyWithEvent:", magnifyWithEvent_),
                             (b"scrollWheel:", scrollWheel_)):
            sel = lib.sel_registerName(sel_name)
            method = lib.class_getInstanceMethod(base_ptr, sel)
            encoding = lib.method_getTypeEncoding(method) if method else None
            added = False
            for enc in (encoding, b"v@:@"):
                if enc is None:
                    continue
                try:
                    objc.classAddMethods(target, [objc.selector(
                        fn, selector=sel_name, signature=enc)])
                    _METHOD_CBS.append(fn)
                    added = True
                    break
                except Exception:
                    continue
            if not added:
                return 0
        _PROBE_CLS = existing
        return existing
    except Exception:
        return 0


def _install_responder_receiver(win) -> bool:
    """RECEIVER B: isa-swizzle *win* onto the probe subclass of its own
    runtime class. Idempotent; verification goes through libobjc (never the
    PyObjC proxy) once the isa has changed; never raises."""
    try:
        import objc
        lib = _libobjc()
        if lib is None:
            return False
        win_ptr = objc.pyobjc_id(win)
        name = lib.object_getClassName(win_ptr)
        if name == _PROBE_PANEL_CLASS_NAME.encode():
            return True
        cls_ptr = _ensure_probe_class(lib, name)
        if not cls_ptr:
            return False
        lib.object_setClass(win_ptr, cls_ptr)
        return lib.object_getClassName(win_ptr) == _PROBE_PANEL_CLASS_NAME.encode()
    except Exception:
        return False


def _window_class_name(win) -> str:
    try:
        import objc
        lib = _libobjc()
        if lib is None:
            return "?"
        return lib.object_getClassName(objc.pyobjc_id(win)).decode()
    except Exception:
        return "?"


def main() -> int:
    app = QApplication(sys.argv)
    print(f"[cp-p1] qt={QtCore.qVersion()} "
          f"platform={QGuiApplication.platformName()} "
          f"macos={platform.mac_ver()[0]}", flush=True)

    w = QWidget(None, Qt.Tool | Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    w.setAttribute(Qt.WA_ShowWithoutActivating)
    w.setAttribute(Qt.WA_TranslucentBackground)
    # A plain QWidget paints no stylesheet background without this.
    w.setAttribute(Qt.WA_StyledBackground)
    w.setObjectName("cpP1Probe")
    w.setStyleSheet(
        "#cpP1Probe { background: rgba(255, 64, 160, 215); }"
        "QLabel { color: white; font-size: 18px; background: transparent; }")
    lay = QVBoxLayout(w)
    label = QLabel("CP-P1 pinch here")
    label.setAlignment(Qt.AlignCenter)
    lay.addWidget(label)
    w.resize(300, 300)
    geo = QGuiApplication.primaryScreen().geometry()
    w.move(geo.center() - QPoint(150, 150))
    w.show()

    if QGuiApplication.platformName() != "cocoa":
        print("[cp-p1] FATAL: QPA is not cocoa - winId() is not an NSView "
              "here and the native calls would crash. Run on the real "
              "session.", file=sys.stderr, flush=True)
        return 1

    win = _nswindow(w)
    if win is None:
        print("[cp-p1] FATAL: could not resolve the NSWindow from winId().",
              file=sys.stderr, flush=True)
        return 1

    panel = _apply_nonactivating(win)
    mask = int(win.styleMask())
    print(f"[cp-p1] window class={_window_class_name(win)} "
          f"styleMask={mask:#x} "
          f"nonactivating={'yes' if mask & _NONACTIVATING_PANEL_MASK else 'NO'} "
          f"panel={'yes' if panel else 'NO'}", flush=True)

    mon_ok = _install_monitor()
    resp_ok = _install_responder_receiver(win)
    print(f"[cp-p1] receiver A (local monitor) installed={mon_ok}", flush=True)
    print(f"[cp-p1] receiver B (responder swizzle) installed={resp_ok} "
          f"class={_window_class_name(win)}", flush=True)

    print("\n[cp-p1] Operator steps (record which receiver lines appear at "
          "each step):\n"
          "  1. Click on ANOTHER app first so this probe's app is INACTIVE.\n"
          "  2. Hover the colored square and pinch in/out on the trackpad.\n"
          "  3. Two-finger scroll over the square.\n"
          "  4. Click the square once, then pinch again (active-app "
          "comparison).\n"
          "  5. Ctrl+C in this terminal to quit.\n", flush=True)

    def _on_sigint(_signum, _frame):
        _remove_monitor()
        app.quit()

    signal.signal(signal.SIGINT, _on_sigint)
    # app.exec parks in native code; a periodic no-op timer returns control
    # to the interpreter so the Python SIGINT handler can actually run.
    wake = QTimer()
    wake.setInterval(200)
    wake.timeout.connect(lambda: None)
    wake.start()

    rc = app.exec()
    _remove_monitor()  # idempotent; covers non-SIGINT exits
    return rc


if __name__ == "__main__":
    sys.exit(main())
