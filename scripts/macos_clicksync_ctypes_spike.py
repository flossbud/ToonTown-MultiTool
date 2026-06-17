#!/usr/bin/env python3
"""Phase-0 spike (THROWAWAY): prove a PURE-CTYPES (no PyObjC) objc_msgSend NSEvent
actuates a background TTR toon via SkyLight, and answer the TCC attribution question.

The inject path imports NO PyObjC. Run it under `/usr/bin/python3 -s` with a scrubbed
env so the operator's --user PyObjC cannot leak in.

Subcommands:
  provenance      pure ctypes: interpreter, csops bits, post-event preflight, AX-trusted
  request-access  pure ctypes: call CGRequestPostEventAccess() and print the result
  resolve         LAZY pyobjc (operator tooling): print inject args for a window id
  inject          pure ctypes: post press+release (or hover) to a background window
"""
import argparse
import ctypes
import os
import sys

CS_PLATFORM_BINARY = 0x04000000
CS_RUNTIME = 0x00010000
CS_OPS_STATUS = 0  # csops op: get status flags


def decode_csflags(flags: int) -> dict:
    return {
        "platform_binary": bool(flags & CS_PLATFORM_BINARY),
        "runtime": bool(flags & CS_RUNTIME),
    }


def csflags_for_pid(pid: int) -> int:
    libc = ctypes.CDLL(None)
    out = ctypes.c_uint32(0)
    libc.csops(int(pid), CS_OPS_STATUS, ctypes.byref(out), ctypes.sizeof(out))
    return int(out.value)


def _cg():
    # CGPreflightPostEventAccess / CGRequestPostEventAccess live in CoreGraphics.
    return ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


def preflight_post_access():
    try:
        fn = _cg().CGPreflightPostEventAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def ax_is_trusted():
    try:
        appserv = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        fn = appserv.AXIsProcessTrusted
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


# --- pure-ctypes Objective-C bridge (no PyObjC) ---
class NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


# selector -> (restype, argtypes AFTER the leading (id self, SEL op)). The two leading
# pointer slots are prepended in _msg(); these argtypes describe the explicit method args.
OBJC_SELECTOR_SIGS = {
    ("mouseEventWithType:location:modifierFlags:timestamp:windowNumber:"
     "context:eventNumber:clickCount:pressure:"): (
        ctypes.c_void_p,
        (ctypes.c_ulong,   # NSEventType type (NSUInteger)
         NSPoint,          # location (by value)
         ctypes.c_ulong,   # modifierFlags (NSUInteger)
         ctypes.c_double,  # timestamp (NSTimeInterval)
         ctypes.c_long,    # windowNumber (NSInteger)
         ctypes.c_void_p,  # context (id, nil)
         ctypes.c_long,    # eventNumber (NSInteger)
         ctypes.c_long,    # clickCount (NSInteger)
         ctypes.c_double), # pressure (CGFloat)
    ),
    "CGEvent": (ctypes.c_void_p, ()),  # -[NSEvent CGEvent] -> CGEventRef
}

_MOUSE_EVENT_SEL = ("mouseEventWithType:location:modifierFlags:timestamp:windowNumber:"
                    "context:eventNumber:clickCount:pressure:")

_libobjc = None


def _objc():
    global _libobjc
    if _libobjc is None:
        lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        lib.objc_autoreleasePoolPush.restype = ctypes.c_void_p
        lib.objc_autoreleasePoolPush.argtypes = []
        lib.objc_autoreleasePoolPop.restype = None
        lib.objc_autoreleasePoolPop.argtypes = [ctypes.c_void_p]
        # AppKit must be loaded so the NSEvent class exists.
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        _libobjc = lib
    return _libobjc


def _msg(receiver, selector_name, restype, arg_types, args):
    """Typed objc_msgSend call: cast a fresh function pointer per selector (never mutate
    a global). receiver is an id/Class pointer; selector_name resolved to a SEL."""
    objc = _objc()
    sel = objc.sel_registerName(selector_name.encode())
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *arg_types)
    fn = proto(("objc_msgSend", objc))
    return fn(ctypes.c_void_p(receiver), ctypes.c_void_p(sel), *args)


def build_ns_cgevent(ns_event_type: int, click_count: int, window_number: int):
    """Return a CGEventRef (int address) for a mouse NSEvent built via objc_msgSend,
    mirroring _NativePort.make_event but with zero PyObjC. None on failure."""
    objc = _objc()
    ns_event_cls = objc.objc_getClass(b"NSEvent")
    restype, argtypes = OBJC_SELECTOR_SIGS[_MOUSE_EVENT_SEL]
    ev = _msg(ns_event_cls, _MOUSE_EVENT_SEL, restype, argtypes,
              (ctypes.c_ulong(int(ns_event_type)),
               NSPoint(0.0, 0.0),
               ctypes.c_ulong(0),
               ctypes.c_double(0.0),
               ctypes.c_long(int(window_number)),
               None,
               ctypes.c_long(0),
               ctypes.c_long(int(click_count)),
               ctypes.c_double(1.0)))
    if not ev:
        return None
    cg_rt, cg_at = OBJC_SELECTOR_SIGS["CGEvent"]
    return _msg(ev, "CGEvent", cg_rt, cg_at, ())


# --- coordinate math + pinned ABI constants ---
# kCGEventSourceUserData=42; kCGEvent* {down:1,up:2,moved:5,dragged:6}. Confirmed live
# against Quartz on macOS 26 (these are stable OS ABI values).
_SOURCE_USER_DATA_FIELD = 42
CGEVENT_TYPE = {"move": 5, "down": 1, "up": 2, "dragged": 6}


def point_from_fraction(bounds, fx, fy):
    """bounds=(x,y,w,h) -> (screen_xy, window_local_xy) for a fractional point. Mirrors
    scripts/macos_framework_spike.screen_point_from_bounds (TTR is borderless, inset 0)."""
    x, y, w, h = bounds
    return (x + w * fx, y + h * fy), (w * fx, h * fy)


_cg_funcs_handle = None


def _cg_funcs():
    """CoreGraphics public setters with argtypes pinned once."""
    global _cg_funcs_handle
    if _cg_funcs_handle is None:
        cg = _cg()
        cg.CGEventSetType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        cg.CGEventSetType.restype = None
        cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        cg.CGEventSetIntegerValueField.restype = None
        _cg_funcs_handle = cg
    return _cg_funcs_handle


def _engine_helpers():
    """Import ONLY the pyobjc-free parts of the production engine. Safe under -s:
    macos_mouse_delivery's top-level imports are stdlib+ctypes; PyObjC is lazy, inside
    _NativePort methods we never call. Handles both the flat (.app Resources) layout and
    the repo (utils/ package) layout."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)                            # flat (.app Resources)
    sys.path.insert(0, os.path.join(here, os.pardir))   # repo root (utils/ package)
    try:
        import macos_mouse_delivery as mmd              # flat layout
    except ImportError:
        from utils import macos_mouse_delivery as mmd   # repo layout
    return mmd


def _resolve_psn(skylight, wid):
    """PSN bytes for a window id via SkyLight (pure ctypes), or None. Mirrors
    _NativePort.resolve_psn."""
    cid = skylight["CGSMainConnectionID"]()
    owner = ctypes.c_uint32(0)
    if int(skylight["SLSGetWindowOwner"](ctypes.c_uint32(int(cid)),
                                         ctypes.c_uint32(int(wid)),
                                         ctypes.byref(owner))) != 0:
        return None
    psn = (ctypes.c_uint32 * 2)()
    if int(skylight["SLSGetConnectionPSN"](ctypes.c_uint32(owner.value),
                                           ctypes.byref(psn))) != 0:
        return None
    return bytes(psn)


def _key_flip(mmd, skylight, wid, psn):
    """The 0x0d activate + two make_key records to the TARGET psn (focus-for-input)."""
    for rec in (mmd.build_activate_record(wid),
                mmd.make_key_record(wid, 0x01),
                mmd.make_key_record(wid, 0x02)):
        skylight["SLPSPostEventRecordTo"](psn, rec)


def _post_event(mmd, skylight, kind, pid, wid, win_xy, screen_xy):
    """Build the mouse CGEvent (pure-ctypes bridge) + stamp the production fields, then
    SLEventPostToPid. Mirrors _build_event + _NativePort.post with zero PyObjC."""
    ns_type = mmd.EVENT_KINDS[kind][0]
    cg = _cg_funcs()
    ev = build_ns_cgevent(ns_type, mmd.click_count_for(kind), wid)
    if not ev:
        return False
    cg.CGEventSetType(ctypes.c_void_p(ev), ctypes.c_uint32(CGEVENT_TYPE[kind]))
    for field, value, via_private in mmd.mouse_event_fields(pid, wid):
        if via_private:
            skylight["SLEventSetIntegerValueField"](
                ctypes.c_void_p(ev), ctypes.c_uint32(int(field)), ctypes.c_int64(int(value)))
        else:
            cg.CGEventSetIntegerValueField(
                ctypes.c_void_p(ev), ctypes.c_uint32(int(field)), ctypes.c_int64(int(value)))
    skylight["CGEventSetWindowLocation"](
        ctypes.c_void_p(ev), mmd._CGPoint(float(win_xy[0]), float(win_xy[1])))
    cg.CGEventSetLocation.argtypes = [ctypes.c_void_p, mmd._CGPoint]
    cg.CGEventSetLocation.restype = None
    cg.CGEventSetLocation(ctypes.c_void_p(ev), mmd._CGPoint(float(screen_xy[0]), float(screen_xy[1])))
    cg.CGEventSetIntegerValueField(
        ctypes.c_void_p(ev), ctypes.c_uint32(_SOURCE_USER_DATA_FIELD),
        ctypes.c_int64(mmd.SPIKE_EVENT_TAG))
    skylight["CGEventSetTimestamp"](ctypes.c_void_p(ev), ctypes.c_uint64(0))
    skylight["SLEventPostToPid"](ctypes.c_int32(int(pid)), ctypes.c_void_p(ev))
    return True


def cmd_inject(args) -> int:
    import time
    mmd = _engine_helpers()
    skylight = mmd._load_skylight()
    if skylight is None:
        print("inject: SkyLight unavailable")
        return 1
    psn = _resolve_psn(skylight, args.wid)
    if psn is None:
        print("inject: could not resolve PSN (window gone?)")
        return 1
    if args.countdown:
        for n in range(args.countdown, 0, -1):
            print(f"focus the TARGET background toon... {n}", flush=True)
            time.sleep(1)
    pool = _objc().objc_autoreleasePoolPush()
    try:
        for _ in range(max(1, args.repeat)):
            if args.kind == "hover":
                _post_event(mmd, skylight, "move", args.pid, args.wid,
                            (args.win_x, args.win_y), (args.screen_x, args.screen_y))
            else:
                _key_flip(mmd, skylight, args.wid, psn)
                _post_event(mmd, skylight, "move", args.pid, args.wid,
                            (args.win_x, args.win_y), (args.screen_x, args.screen_y))
                _post_event(mmd, skylight, "down", args.pid, args.wid,
                            (args.win_x, args.win_y), (args.screen_x, args.screen_y))
                _post_event(mmd, skylight, "up", args.pid, args.wid,
                            (args.win_x, args.win_y), (args.screen_x, args.screen_y))
    finally:
        _objc().objc_autoreleasePoolPop(pool)
    print(f"inject: posted {args.kind} pid={args.pid} wid={args.wid} x{max(1, args.repeat)}")
    return 0


def cmd_resolve(args) -> int:
    """LAZY pyobjc (operator tooling): print a ready-to-paste `inject` arg line for a
    window id + fractional click point. Reuses the proven macos_discovery resolution."""
    from utils import macos_discovery as disc  # pyobjc; operator python only
    bounds = disc.get_window_geometry_fresh(args.wid)
    pid = disc.get_window_pid(args.wid)
    if not bounds or pid is None:
        print(f"resolve: could not resolve wid={args.wid} (bounds={bounds} pid={pid})")
        return 1
    scr, win = point_from_fraction(bounds, args.frac_x, args.frac_y)
    print(f"--pid {pid} --wid {args.wid} --win-x {win[0]} --win-y {win[1]} "
          f"--screen-x {scr[0]} --screen-y {scr[1]}")
    return 0


def cmd_provenance(args) -> int:
    flags = csflags_for_pid(os.getpid())
    info = {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "uname": os.uname().release,
        "machine": os.uname().machine,
        "csflags": hex(flags),
        **decode_csflags(flags),
        "preflight_post_access": preflight_post_access(),
        "ax_is_trusted": ax_is_trusted(),
    }
    for k, v in info.items():
        print(f"{k}={v}")
    return 0


def cmd_request_access(args) -> int:
    """Trigger the OS Accessibility (post-event) prompt for THIS process identity and
    print the result. On a clean account this reveals whether the prompt attributes to
    the app or to Python (spec 6.7)."""
    try:
        fn = _cg().CGRequestPostEventAccess
        fn.restype = ctypes.c_bool
        granted = bool(fn())
    except Exception as e:
        print(f"request-access error: {type(e).__name__}: {e}")
        return 1
    print(f"request_post_access_granted={granted}")
    print(f"preflight_after={preflight_post_access()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase-0 pure-ctypes click-sync spike")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("provenance")
    sub.add_parser("request-access")
    pr = sub.add_parser("resolve")
    pr.add_argument("--wid", type=int, required=True)
    pr.add_argument("--frac-x", type=float, default=0.5)
    pr.add_argument("--frac-y", type=float, default=0.5)
    pi = sub.add_parser("inject")
    pi.add_argument("--pid", type=int, required=True)
    pi.add_argument("--wid", type=int, required=True)
    pi.add_argument("--win-x", type=float, required=True)
    pi.add_argument("--win-y", type=float, required=True)
    pi.add_argument("--screen-x", type=float, required=True)
    pi.add_argument("--screen-y", type=float, required=True)
    pi.add_argument("--kind", choices=["click", "hover"], default="click")
    pi.add_argument("--countdown", type=int, default=0)
    pi.add_argument("--repeat", type=int, default=1)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "provenance":
        return cmd_provenance(args)
    if args.cmd == "request-access":
        return cmd_request_access(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)          # Task 3
    if args.cmd == "inject":
        return cmd_inject(args)           # Task 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
