"""macOS Click Sync mouse delivery engine (private SkyLight per-window path).

Pure record/field builders (this section) + the native delivery engine (Task 2).
Mechanism + record bytes proven in scripts/macos_click_delivery_spike.py and
docs/superpowers/specs/2026-06-13-macos-click-sync-port-design.md Section 2. The
pure helpers below carry NO PyObjC import so they unit-test on any host.
"""
from __future__ import annotations

import time

# kCGEventSourceUserData marker stamped on every posted event (echo filter).
# Same value as utils.macos_backend.SPIKE_EVENT_TAG so capture filters both paths.
SPIKE_EVENT_TAG = 0x7474_6D74  # "ttmt"

LEDGER_TTL = 0.25  # seconds a posted-event signature stays "ours" for echo matching

FOCUS_RECORD_SIZE = 0xF8  # 248-byte SkyLight event record


def build_activate_record(window_id: int) -> bytes:
    """The 0x0d "focused app for input routing" record (cua/yabai), posted to the
    TARGET PSN. Bytes: [0x04]=0xF8, [0x08]=0x0D, [0x3C:0x40]=wid (LE u32), [0x8A]=0x01."""
    rec = bytearray(FOCUS_RECORD_SIZE)
    rec[0x04] = 0xF8
    rec[0x08] = 0x0D
    rec[0x3C:0x40] = int(window_id).to_bytes(4, "little")
    rec[0x8A] = 0x01
    return bytes(rec)


def make_key_record(window_id: int, mode: int) -> bytes:
    """yabai make_key_window record, posted TWICE to the TARGET PSN (mode 0x01 then
    0x02). Bytes: [0x04]=0xF8, [0x08]=mode, [0x3A]=0x10, [0x3C:0x40]=wid (LE u32),
    [0x20:0x30]=0xff."""
    rec = bytearray(FOCUS_RECORD_SIZE)
    rec[0x04] = 0xF8
    rec[0x08] = int(mode) & 0xFF
    rec[0x3A] = 0x10
    rec[0x3C:0x40] = int(window_id).to_bytes(4, "little")
    for i in range(0x20, 0x30):
        rec[i] = 0xFF
    return bytes(rec)


def mouse_event_fields(pid: int, window_id: int) -> list[tuple[int, int, bool]]:
    """(field_id, value, via_private) stamped on every mouse CGEvent. Proven values
    from the spike's positive control. Private fields use SLEventSetIntegerValueField."""
    return [
        (1, 1, False),         # kCGMouseEventClickState
        (3, 0, False),         # kCGMouseEventButtonNumber (left = 0)
        (7, 3, False),         # kCGMouseEventSubtype
        (40, int(pid), True),  # kCGEventTargetUnixProcessID (private setter)
        (91, int(window_id), True),
        (92, int(window_id), True),
    ]


# kind -> (NSEventType int, Quartz CGEventType attribute name). The native layer
# resolves the attribute name against the Quartz module at post time.
EVENT_KINDS = {
    "move":    (5, "kCGEventMouseMoved"),
    "down":    (1, "kCGEventLeftMouseDown"),
    "up":      (2, "kCGEventLeftMouseUp"),
    "dragged": (6, "kCGEventLeftMouseDragged"),
}


def click_count_for(kind: str) -> int:
    """NSEvent clickCount: 0 for a bare move, 1 for button-bearing events."""
    return 0 if kind == "move" else 1


class EchoLedger:
    """Shared record of recently POSTED event signatures. The SAME instance is wired
    into the delivery engine (which `record`s every posted event) and the capture
    EchoGuard (which `matches` to recognize an injected event that re-entered the tap
    WITHOUT our marker - a marker-stripping OS revision). Signature buckets the screen
    point so float jitter still matches. Event-type ints are the mouse CGEventType
    values, which equal the NSEventType values for these kinds (down=1, up=2, moved=5,
    dragged=6), so the delivery side (NSEventType) and the capture side (CGEventType)
    agree on the key. Single-threaded use (the dispatcher thread) - no lock needed."""

    def __init__(self, ttl: float = LEDGER_TTL):
        self._ttl = float(ttl)
        self._sigs: dict[tuple[int, int, int], float] = {}   # signature -> expiry (monotonic)

    @staticmethod
    def _sig(event_type: int, root_x: float, root_y: float) -> tuple[int, int, int]:
        return (int(event_type), round(float(root_x) / 2), round(float(root_y) / 2))

    def _evict(self, t: float) -> None:
        """Drop expired signatures. Called from BOTH record() and matches() so the
        dict stays bounded even when one side is idle (e.g. the delivery engine posts
        while capture is stopped, so matches() is never called)."""
        for k in [k for k, exp in self._sigs.items() if exp < t]:
            self._sigs.pop(k, None)

    def record(self, event_type: int, root_x: float, root_y: float, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        self._evict(t)
        self._sigs[self._sig(event_type, root_x, root_y)] = t + self._ttl

    def matches(self, event_type: int, root_x: float, root_y: float, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        self._evict(t)
        exp = self._sigs.get(self._sig(event_type, root_x, root_y))
        return exp is not None and exp >= t


# ── native delivery engine (lazy PyObjC + ctypes; operator-validated) ──────────
import ctypes

# name -> (restype, argtypes) strings; resolved in _load_skylight(). Deliberately
# NO _SLPSGetFrontProcess / _SLPSSetFrontProcessWithOptions: we never defocus the
# source and never raise (spec §2.2).
_SKYLIGHT_SYMBOLS = {
    "CGSMainConnectionID":         ("uint32", ()),
    "SLSGetWindowOwner":           ("int32", ("uint32", "uint32", "ptr")),
    "SLSGetConnectionPSN":         ("int32", ("uint32", "ptr")),
    "SLPSPostEventRecordTo":       ("int32", ("ptr", "ptr")),
    "CGEventSetWindowLocation":    ("void", ("ptr", "cgpoint")),
    "SLEventSetIntegerValueField": ("void", ("ptr", "uint32", "int64")),
    "CGEventSetTimestamp":         ("void", ("ptr", "uint64")),
    "SLEventPostToPid":            ("void", ("pid", "ptr")),
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _load_skylight():
    """dlopen SkyLight + declare _SKYLIGHT_SYMBOLS. Returns name->callable, or None
    if the framework or ANY symbol is missing (the engine then reports unavailable)."""
    _CTYPE = {
        "void": None, "uint32": ctypes.c_uint32, "int32": ctypes.c_int32,
        "uint64": ctypes.c_uint64, "int64": ctypes.c_int64,
        "pid": ctypes.c_int32, "ptr": ctypes.c_void_p, "cgpoint": _CGPoint,
    }
    try:
        sky = ctypes.CDLL("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight")
    except Exception:
        return None
    out = {}
    for name, (restype, argtypes) in _SKYLIGHT_SYMBOLS.items():
        try:
            fn = getattr(sky, name)
        except AttributeError:
            return None
        fn.restype = _CTYPE[restype]
        fn.argtypes = tuple(_CTYPE[a] for a in argtypes)
        out[name] = fn
    return out


# ── pure-ctypes Objective-C bridge (NO PyObjC) ─────────────────────────────────
# The shipped engine injects through a /usr/bin/python3 (Apple platform-binary)
# helper that has NO PyObjC, so the NSEvent->CGEvent construction must run on raw
# libobjc objc_msgSend. This keeps the exact `NSEvent.CGEvent()` semantics (NOT
# CGEventCreateMouseEvent, which WindowServer treats differently). Ported verbatim
# from the live-proven scripts/macos_clicksync_ctypes_spike.py.


class _NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_MOUSE_EVENT_SEL = ("mouseEventWithType:location:modifierFlags:timestamp:windowNumber:"
                    "context:eventNumber:clickCount:pressure:")

# selector -> (restype, argtypes AFTER the leading (id self, SEL op)). The two leading
# pointer slots are prepended in _msg(); these argtypes describe the explicit method args.
_OBJC_SELECTOR_SIGS = {
    _MOUSE_EVENT_SEL: (
        ctypes.c_void_p,
        (ctypes.c_ulong,   # NSEventType type (NSUInteger)
         _NSPoint,         # location (by value)
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

_libobjc = None


def _objc():
    """dlopen libobjc + AppKit (so the NSEvent class exists); argtypes pinned once.
    Returns the libobjc handle. Pure ctypes, safe under a scrubbed no-PyObjC python."""
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


def _build_ns_cgevent(ns_event_type, click_count, window_number):
    """Return a CGEventRef (int address) for a mouse NSEvent built via objc_msgSend,
    keeping the exact NSEvent.CGEvent() semantics with zero PyObjC. None on failure."""
    objc = _objc()
    ns_event_cls = objc.objc_getClass(b"NSEvent")
    restype, argtypes = _OBJC_SELECTOR_SIGS[_MOUSE_EVENT_SEL]
    ev = _msg(ns_event_cls, _MOUSE_EVENT_SEL, restype, argtypes,
              (ctypes.c_ulong(int(ns_event_type)),
               _NSPoint(0.0, 0.0),
               ctypes.c_ulong(0),
               ctypes.c_double(0.0),
               ctypes.c_long(int(window_number)),
               None,
               ctypes.c_long(0),
               ctypes.c_long(int(click_count)),
               ctypes.c_double(1.0)))
    if not ev:
        return None
    cg_rt, cg_at = _OBJC_SELECTOR_SIGS["CGEvent"]
    return _msg(ev, "CGEvent", cg_rt, cg_at, ())


# kCGEventSourceUserData=42; kCGEvent* {down:1,up:2,moved:5,dragged:6}. Stable OS ABI
# values confirmed live against Quartz on macOS 26.
_CG_USER_DATA_FIELD = 42
_CGEVENT_TYPE = {"move": 5, "down": 1, "up": 2, "dragged": 6}


def _load_coregraphics():
    """CoreGraphics public CGEvent setters with argtypes pinned once (pure ctypes, no
    PyObjC). Returns the CDLL handle the native port calls."""
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGEventSetType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    cg.CGEventSetType.restype = None
    cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
    cg.CGEventSetIntegerValueField.restype = None
    cg.CGEventSetLocation.argtypes = [ctypes.c_void_p, _CGPoint]
    cg.CGEventSetLocation.restype = None
    return cg


def _push_autorelease_pool():
    """Push an ObjC autorelease pool so the autoreleased NSEvents built in make_event
    get reclaimed when popped (there is no run loop to drain them). Returns the pool
    token, or None when the ObjC runtime is unavailable (non-macOS hosts running the
    engine orchestration tests against an injected fake port)."""
    try:
        return _objc().objc_autoreleasePoolPush()
    except Exception:
        return None


def _pop_autorelease_pool(pool):
    if pool is None:
        return
    try:
        _objc().objc_autoreleasePoolPop(pool)
    except Exception:
        pass


class _NativePort:
    """Real CoreGraphics/SkyLight port via pure ctypes (NO PyObjC); the engine's single
    native seam. Events flow as raw CGEventRef integer addresses (from _build_ns_cgevent)
    and every native call wraps them in c_void_p."""
    def __init__(self, cg, sky):
        self._cg = cg
        self._sky = sky

    def make_event(self, kind, click_count, window_number):
        ns_type = EVENT_KINDS[kind][0]
        ev = _build_ns_cgevent(ns_type, click_count, window_number)
        if ev:  # fail-closed: a null build (e.g. AppKit/objc init failed) must not be posted
            self._cg.CGEventSetType(ctypes.c_void_p(ev), _CGEVENT_TYPE[kind])
        return ev

    def set_public_field(self, ev, field, value):
        self._cg.CGEventSetIntegerValueField(
            ctypes.c_void_p(ev), ctypes.c_uint32(int(field)), ctypes.c_int64(int(value)))

    def set_private_field(self, ev, field, value):
        self._sky["SLEventSetIntegerValueField"](
            ctypes.c_void_p(ev), ctypes.c_uint32(int(field)), ctypes.c_int64(int(value)))

    def set_window_location(self, ev, pt):
        self._sky["CGEventSetWindowLocation"](
            ctypes.c_void_p(ev), _CGPoint(float(pt[0]), float(pt[1])))

    def set_location(self, ev, pt):
        self._cg.CGEventSetLocation(ctypes.c_void_p(ev), _CGPoint(float(pt[0]), float(pt[1])))

    def set_source_user_data(self, ev, tag):
        self._cg.CGEventSetIntegerValueField(
            ctypes.c_void_p(ev), ctypes.c_uint32(_CG_USER_DATA_FIELD), ctypes.c_int64(int(tag)))

    def post(self, pid, ev):
        # LOAD-BEARING: WindowServer silently drops a 0-timestamp event as stale; a real
        # monotonic_ns stamp is required (live-proven 2026-06-17 in the ctypes spike).
        self._sky["CGEventSetTimestamp"](ctypes.c_void_p(ev), ctypes.c_uint64(time.monotonic_ns()))
        self._sky["SLEventPostToPid"](ctypes.c_int32(int(pid)), ctypes.c_void_p(ev))

    def post_record(self, psn_bytes, record_bytes) -> int:
        return int(self._sky["SLPSPostEventRecordTo"](psn_bytes, record_bytes))

    def resolve_psn(self, window_id):
        sky = self._sky
        cid = sky["CGSMainConnectionID"]()
        owner = ctypes.c_uint32(0)
        if int(sky["SLSGetWindowOwner"](ctypes.c_uint32(int(cid)),
                                        ctypes.c_uint32(int(window_id)),
                                        ctypes.byref(owner))) != 0:
            return None
        psn = (ctypes.c_uint32 * 2)()
        if int(sky["SLSGetConnectionPSN"](ctypes.c_uint32(owner.value),
                                          ctypes.byref(psn))) != 0:
            return None
        return bytes(psn)

    def resolve_owner(self, window_id):
        sky = self._sky
        cid = sky["CGSMainConnectionID"]()
        owner = ctypes.c_uint32(0)
        if int(sky["SLSGetWindowOwner"](ctypes.c_uint32(int(cid)),
                                        ctypes.c_uint32(int(window_id)),
                                        ctypes.byref(owner))) != 0:
            return None
        return int(owner.value)


def _build_event(port, kind, win_xy, screen_xy, pid, window_id):
    ev = port.make_event(kind, click_count_for(kind), window_id)
    if ev is None:   # fail-closed: never stamp/post a NULL event
        return None
    for field, value, via_private in mouse_event_fields(pid, window_id):
        (port.set_private_field if via_private else port.set_public_field)(ev, field, value)
    port.set_window_location(ev, (float(win_xy[0]), float(win_xy[1])))
    port.set_location(ev, (float(screen_xy[0]), float(screen_xy[1])))
    port.set_source_user_data(ev, SPIKE_EVENT_TAG)
    return ev


_DIAG_LOG: list[str] = []   # one-line ABI diagnostics; appended ONCE per engine (spec §3.1)

_UNSET = object()   # sentinel: "no port supplied → lazy-load on first use"


class MacOSMouseDelivery:
    """Per-window mouse delivery via the SkyLight key-flip + SLEventPostToPid path
    (spec §2.2/§3.1). Receives already-resolved (pid, wid, psn) + already-mapped
    window-local and screen points; owns NO identity validation. A True result means
    "post attempted," NOT delivery accepted (SLEventPostToPid is fire-and-forget).
    `port` is injectable for tests; pass port=None to force unavailable (no lazy load)."""

    # No move->down gap: Panda's AppKit event queue preserves order, so the move
    # (rollover) is processed before the down (actuation) without an inter-phase
    # sleep. The spike's 16ms was conservative cargo (spec §2.3 flagged it as such);
    # 0 is live-validated reliable and removes the perceptible per-click delay.
    AFTER_MOVE_S = 0.0
    DOWN_TO_UP_S = 0.001

    def __init__(self, port=_UNSET, ledger=None):
        self._port = None if port is _UNSET else port
        self._ledger = ledger   # shared EchoLedger (records posts for the capture's echo guard)
        self._tried_load = port is not _UNSET   # False only when omitted → lazy-load
        self._faulted = False

    def _get_port(self):
        if self._port is None and not self._tried_load:
            self._tried_load = True
            try:
                sky = _load_skylight()
                self._port = _NativePort(_load_coregraphics(), sky) if sky is not None else None
                if self._port is None:
                    self._diag_once("load")   # framework/symbol missing
            except Exception:
                self._port = None
                self._diag_once("load")       # surface real ctypes load failures
        return self._port

    @property
    def available(self) -> bool:
        return (not self._faulted) and (self._get_port() is not None)

    def resolve_psn(self, window_id):
        port = self._get_port()
        if port is None:
            return None
        try:
            return port.resolve_psn(window_id)
        except Exception:
            return None

    def resolve_owner(self, window_id):
        """The SkyLight owner CONNECTION id for the window (part of the gesture identity
        binding, Task 3), or None. Distinct from the PSN."""
        port = self._get_port()
        if port is None:
            return None
        try:
            return port.resolve_owner(window_id)
        except Exception:
            return None

    def _diag_once(self, phase: str) -> None:
        """Append a ONE-TIME ABI diagnostic line (spec §3.1): OS build, arch, how many
        SkyLight symbols resolved, and the failing phase. Idempotent per engine."""
        if getattr(self, "_diag_done", False):
            return
        self._diag_done = True
        import platform, os
        port = self._port
        n_sym = len(port._sky) if (port is not None and hasattr(port, "_sky")) else 0
        # mac_ver()[0] is the product VERSION (e.g. "26.0"), not the build; the Darwin
        # kernel release (uname) is the closest no-subprocess proxy for ABI correlation.
        try:
            darwin = os.uname().release
        except Exception:
            darwin = "?"
        line = (f"[macos_mouse_delivery] DIAG phase={phase} macos={platform.mac_ver()[0]!r} "
                f"darwin={darwin!r} arch={platform.machine()!r} "
                f"symbols={n_sym}/{len(_SKYLIGHT_SYMBOLS)} faulted={self._faulted}")
        _DIAG_LOG.append(line)
        print(line)

    def key_flip(self, window_id, psn) -> bool:
        """Post the 0x0d activate + two make_key records to the TARGET psn. A nonzero
        record status (or an exception) is a STICKY fault."""
        port = self._get_port()
        if port is None:
            return False
        pool = _push_autorelease_pool()
        try:
            for rec in (build_activate_record(window_id),
                        make_key_record(window_id, 0x01),
                        make_key_record(window_id, 0x02)):
                if port.post_record(psn, rec) != 0:
                    self._faulted = True
                    self._diag_once("record")
                    return False
            return True
        except Exception:
            self._faulted = True
            self._diag_once("record")
            return False
        finally:
            _pop_autorelease_pool(pool)

    def _post(self, kind, pid, wid, win_xy, screen_xy) -> bool:
        port = self._get_port()
        if port is None:
            return False
        pool = _push_autorelease_pool()
        try:
            ev = _build_event(port, kind, win_xy, screen_xy, pid, wid)
            if ev is None:   # null build -> fault, never post NULL / record a phantom echo
                self._faulted = True
                self._diag_once("post")
                return False
            port.post(pid, ev)
            if self._ledger is not None:
                # Record the SCREEN signature so the capture's EchoGuard can recognize a
                # marker-stripped echo of THIS post. EVENT_KINDS[kind][0] is the mouse
                # CGEventType the tap will observe.
                self._ledger.record(EVENT_KINDS[kind][0], screen_xy[0], screen_xy[1])
            return True
        except Exception:
            self._faulted = True
            self._diag_once("post")
            return False
        finally:
            _pop_autorelease_pool(pool)

    def press(self, pid, wid, psn, win_xy, screen_xy) -> bool:
        """key_flip -> move -> down. On a down failure (it may have partially posted),
        best-effort a compensating up. Does NOT post the up (release is separate)."""
        if not self.available:
            return False
        if not self.key_flip(wid, psn):
            return False
        if not self._post("move", pid, wid, win_xy, screen_xy):
            return False
        time.sleep(self.AFTER_MOVE_S)
        if not self._post("down", pid, wid, win_xy, screen_xy):
            self._post("up", pid, wid, win_xy, screen_xy)   # never leave it stuck
            return False
        time.sleep(self.DOWN_TO_UP_S)
        return True

    def motion(self, pid, wid, psn, win_xy, screen_xy, dragging: bool) -> bool:
        """A dragged event (button held) or a bare move (hover). NO key-flip: a drag's
        key state persists from the press; hover needs none."""
        if not self.available:
            return False
        return self._post("dragged" if dragging else "move", pid, wid, win_xy, screen_xy)

    def release(self, pid, wid, psn, win_xy, screen_xy) -> bool:
        """The up. NO key-flip."""
        if not self.available:
            return False
        return self._post("up", pid, wid, win_xy, screen_xy)
