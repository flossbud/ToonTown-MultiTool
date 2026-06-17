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
