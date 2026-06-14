#!/usr/bin/env python3
"""macOS Click Sync delivery spike (Phase 0b). Standalone operator probe.

Tests the private SkyLight per-window delivery path (SLEventPostToPid) the first
spike never tried, plus the time-slice and injection fallback rungs. Spec:
docs/superpowers/specs/2026-06-13-macos-click-delivery-spike-design.md.

Usage:
  python3 scripts/macos_click_delivery_spike.py list
  python3 scripts/macos_click_delivery_spike.py probe-rect <pid> [--inset N]
  python3 scripts/macos_click_delivery_spike.py sl-click <pid> <window_id> [flags]
  python3 scripts/macos_click_delivery_spike.py sl-gesture <pid> <window_id> --kind drag|hover [flags]
  python3 scripts/macos_click_delivery_spike.py sl-fanout <pidA> <widA> <pidB> <widB> [flags]
  python3 scripts/macos_click_delivery_spike.py sl-positive-control <fg_pid> <wid> [--frac FX FY]
  python3 scripts/macos_click_delivery_spike.py sl-echo <pid> <window_id> [--seconds N]
  python3 scripts/macos_click_delivery_spike.py timeslice-click <pidA> <pidB> [--inset N]
  python3 scripts/macos_click_delivery_spike.py timeslice-drag <pidA> <pidB> [--inset N]
  python3 scripts/macos_click_delivery_spike.py inject-preflight <pid>

PyObjC + the private SkyLight symbols are loaded lazily, so this file imports on any
platform; the pure helpers below are unit-tested on Linux/Windows CI.
"""
from __future__ import annotations

import ctypes
import dataclasses
import os
import sys
import threading
import time

# Reuse the sibling spikes' tested helpers (same dir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macos_input_spike as kb   # noqa: E402  (path insert must precede import)
import macos_mouse_spike as ms   # noqa: E402

SPIKE_EVENT_TAG = kb.SPIKE_EVENT_TAG
content_rect = ms.content_rect
content_point_to_global = ms.content_point_to_global


# ── pure byte-layout helpers ───────────────────────────────────────────────
FOCUS_RECORD_SIZE = 0xF8  # 248-byte SkyLight event record (cua, inferred ABI)


def build_focus_record(window_id: int, mode: int) -> bytes:
    """The 248-byte focus-without-raise record for SLPSPostEventRecordTo.

    Offsets are cua's reverse-engineered layout (see spec 2.2): a header tag,
    the target CGWindowID as a u32 LE, and a mode byte (0x01 focus, 0x02 defocus).
    Everything else is zero. Treated as a hypothesis the live spike confirms.
    """
    rec = bytearray(FOCUS_RECORD_SIZE)
    rec[0x04] = 0xF8
    rec[0x08] = 0x0D
    rec[0x3C:0x40] = int(window_id).to_bytes(4, "little")
    rec[0x8A] = int(mode) & 0xFF
    return bytes(rec)


def pack_psn(psn: tuple[int, int]) -> bytes:
    """A ProcessSerialNumber is two UInt32 (8 bytes total)."""
    hi, lo = psn
    return int(hi).to_bytes(4, "little") + int(lo).to_bytes(4, "little")


def unpack_psn(buf: bytes) -> tuple[int, int]:
    """Inverse of pack_psn; reads the first 8 bytes."""
    return (int.from_bytes(buf[0:4], "little"), int.from_bytes(buf[4:8], "little"))


# ── pure event field table + timing ────────────────────────────────────────
# (field_id, value, via_private). Field ids + private-setter choice are taken
# verbatim from cua's MouseInput.swift; the spike's positive control confirms.
def mouse_event_fields(pid: int, window_id: int) -> list[tuple[int, int, bool]]:
    """Ordered integer fields to stamp on every mouse CGEvent."""
    return [
        (1, 1, False),            # kCGMouseEventClickState
        (3, 0, False),            # kCGMouseEventButtonNumber (left = 0)
        (7, 3, False),            # kCGMouseEventSubtype
        (40, int(pid), True),     # kCGEventTargetUnixProcessID (private setter)
        (91, int(window_id), True),
        (92, int(window_id), True),
    ]


_TIMING_BASE = {
    "zero": {"after_move": 0.0, "primer_internal": 0.0,
             "primer_to_target": 0.0, "down_to_up": 0.0},
    "1ms": {"after_move": 0.001, "primer_internal": 0.001,
            "primer_to_target": 0.001, "down_to_up": 0.001},
    "16ms": {"after_move": 0.016, "primer_internal": 0.001,
             "primer_to_target": 0.001, "down_to_up": 0.001},
    "cua": {"after_move": 0.015, "primer_internal": 0.001,
            "primer_to_target": 0.100, "down_to_up": 0.001},
}
TIMING_PROFILES = tuple(_TIMING_BASE)


def timing_gaps(profile: str, has_primer: bool) -> dict:
    """Per-phase-boundary sleeps (seconds) for a timing profile.

    Without a primer, the two primer-related gaps are zeroed (there is no primer
    pair to space out); the move and down->up gaps are unaffected.
    """
    if profile not in _TIMING_BASE:
        raise ValueError(f"unknown timing profile {profile!r}; choose {TIMING_PROFILES}")
    gaps = dict(_TIMING_BASE[profile])
    if not has_primer:
        gaps["primer_internal"] = 0.0
        gaps["primer_to_target"] = 0.0
    return gaps


# ── pure event-spec builders ───────────────────────────────────────────────
OFF_WINDOW_POINT = (-1.0, -1.0)  # the off-window primer pair's position (cua)


def _as_point(p) -> tuple:
    """Coerce a coordinate pair to (float, float) so every spec carries floats
    regardless of int/float input (uniform across all builders)."""
    return (float(p[0]), float(p[1]))


@dataclasses.dataclass(frozen=True)
class EventSpec:
    """One event to post. `point` is a window-LOCAL point (the native layer also
    derives the screen point). `primer` marks the off-window user-activation pair.
    kind in {move, down, up, dragged}."""
    kind: str
    point: tuple
    click_count: int
    primer: bool = False


def click_event_specs(point: tuple, primer: bool) -> list[EventSpec]:
    """move(point) -> [primer down/up off-window] -> down(point) -> up(point).

    The leading move is required: Panda reads click position from the preceding
    motion event, not from the down (spec 1.2). The primer pair is an optional
    Chromium-style user-activation hack, tested with and without.
    """
    point = _as_point(point)
    specs = [EventSpec("move", point, 0)]
    if primer:
        specs.append(EventSpec("down", OFF_WINDOW_POINT, 1, primer=True))
        specs.append(EventSpec("up", OFF_WINDOW_POINT, 1, primer=True))
    specs.append(EventSpec("down", point, 1))
    specs.append(EventSpec("up", point, 1))
    return specs


def hover_event_specs(points: list[tuple]) -> list[EventSpec]:
    """Unclicked motion: a mouseMoved per point, no buttons."""
    return [EventSpec("move", _as_point(p), 0) for p in points]


def drag_event_specs(from_pt: tuple, to_pt: tuple, steps: int) -> list[EventSpec]:
    """move(from) -> down(from) -> `steps` dragged points -> up(to).

    `steps` interior dragged events are linearly interpolated from `from_pt`
    (exclusive) toward `to_pt` (inclusive of the final dragged sample); the
    closing up is at `to_pt`. Every event after the move carries click_count 1.
    """
    if steps < 1:
        raise ValueError("drag needs steps >= 1")
    fx, fy = _as_point(from_pt)
    tx, ty = _as_point(to_pt)
    specs = [EventSpec("move", (fx, fy), 0), EventSpec("down", (fx, fy), 1)]
    for i in range(1, steps + 1):
        t = i / steps
        specs.append(EventSpec("dragged", (fx + (tx - fx) * t, fy + (ty - fy) * t), 1))
    specs.append(EventSpec("up", (tx, ty), 1))
    return specs


def fanout_phase_plan(target_ids: list, point: tuple) -> list[tuple]:
    """Phase-wise broadcast plan to N targets: ALL moves, then ALL downs, then ALL
    ups. Returns [(phase, target_id, EventSpec), ...].

    This is the production fan-out shape (spec 2.4): the per-click delay is paid
    ONCE per phase, not once per target, so N toons do not stack N x timing lag.
    """
    if not target_ids:
        raise ValueError("fanout needs at least one target")
    point = _as_point(point)  # uniform with the other builders
    phases = [("move", 0), ("down", 1), ("up", 1)]
    plan = []
    for kind, cc in phases:
        for tid in target_ids:
            plan.append((kind, tid, EventSpec(kind, point, cc)))
    return plan


# ── pure CLI parsing ───────────────────────────────────────────────────────
class ArgError(ValueError):
    """Raised for invalid spike CLI arguments (caught by command bodies)."""


@dataclasses.dataclass
class SLArgs:
    positionals: list
    focus: bool = False
    primer: bool = False
    restore_focus: bool = False
    timing: str = "1ms"
    inset: int = 0
    frac: tuple = (0.5, 0.5)
    frm: tuple = (0.05, 0.5)
    to: tuple = (0.95, 0.5)
    hold: float = 0.0
    reps: int = 1
    kind: str | None = None


_BOOL_FLAGS = {"--focus": "focus", "--primer": "primer",
               "--restore-focus": "restore_focus"}
_PAIR_FLAGS = {"--frac": "frac", "--from": "frm", "--to": "to"}
_VALUE_FLAGS = {"--timing": ("timing", str), "--inset": ("inset", int),
                "--hold": ("hold", float), "--reps": ("reps", int),
                "--kind": ("kind", str)}


def parse_sl_args(rest: list) -> SLArgs:
    """Parse the shared sl-* flag grammar into an SLArgs. Raises ArgError on
    misuse (missing/bad value, unknown flag, --restore-focus without --focus,
    unknown --timing/--kind, non-positive --reps, negative --inset)."""
    out = SLArgs(positionals=[])

    def _val(idx, tok):
        # the next token as a value; a missing token or another flag (-- prefix,
        # NOT a single '-' so negative numbers still parse) is a usage error.
        if idx >= len(rest) or rest[idx].startswith("--"):
            raise ArgError(f"{tok} needs a value")
        return rest[idx]

    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in _BOOL_FLAGS:
            setattr(out, _BOOL_FLAGS[tok], True)
            i += 1
        elif tok in _PAIR_FLAGS:
            try:
                fx, fy = float(_val(i + 1, tok)), float(_val(i + 2, tok))
            except ValueError:
                raise ArgError(f"{tok} needs two float values")
            setattr(out, _PAIR_FLAGS[tok], (fx, fy))
            i += 3
        elif tok in _VALUE_FLAGS:
            attr, typ = _VALUE_FLAGS[tok]
            try:
                setattr(out, attr, typ(_val(i + 1, tok)))
            except ValueError:
                raise ArgError(f"{tok} needs a {typ.__name__} value")
            i += 2
        elif tok.startswith("--"):
            raise ArgError(f"unknown flag {tok!r}")
        else:
            out.positionals.append(tok)
            i += 1
    if out.timing not in TIMING_PROFILES:
        raise ArgError(f"--timing must be one of {TIMING_PROFILES}")
    if out.kind is not None and out.kind not in ("hover", "drag"):
        raise ArgError("--kind must be hover or drag")
    if out.restore_focus and not out.focus:
        raise ArgError("--restore-focus requires --focus (nothing to restore otherwise)")
    if out.reps < 1:
        raise ArgError("--reps must be >= 1")
    if out.inset < 0:
        raise ArgError("--inset must be >= 0")
    return out


# ── native SkyLight glue (lazy; operator-validated) ────────────────────────
# name -> (restype, argtypes). ctypes types resolved in _skylight(); kept as
# strings here so the table is importable + unit-testable without ctypes loaded.
SKYLIGHT_SYMBOLS = {
    "CGSMainConnectionID":      ("uint32", ()),
    "SLSGetWindowOwner":        ("int32", ("uint32", "uint32", "ptr")),
    "SLSGetConnectionPSN":      ("int32", ("uint32", "ptr")),
    "_SLPSGetFrontProcess":     ("int32", ("ptr",)),
    "SLPSPostEventRecordTo":    ("int32", ("ptr", "ptr")),
    "CGEventSetWindowLocation": ("void", ("ptr", "cgpoint")),
    "SLEventSetIntegerValueField": ("void", ("ptr", "uint32", "int64")),
    "CGEventSetTimestamp":      ("void", ("ptr", "uint64")),
    "SLEventPostToPid":         ("void", ("pid", "ptr")),
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _as_ptr(cg_event):
    """A PyObjC CGEventRef -> a ctypes c_void_p for the private SkyLight calls."""
    import objc
    return ctypes.c_void_p(objc.pyobjc_id(cg_event))


class _SkyPort:
    """Seam over NSEvent construction + Quartz/SkyLight stamping. The fake in the
    test mirrors this surface; the real one is built by _skylight()."""
    def __init__(self, quartz, sky):
        self._q = quartz      # Quartz module (PyObjC)
        self._sky = sky       # ctypes-wrapped SkyLight symbols (dict name->callable)

    def make_event(self, kind, click_count, window_number):
        import Quartz
        from AppKit import NSEvent
        type_map = {
            "move": Quartz.kCGEventMouseMoved,
            "down": Quartz.kCGEventLeftMouseDown,
            "up": Quartz.kCGEventLeftMouseUp,
            "dragged": Quartz.kCGEventLeftMouseDragged,
        }
        ns_type_map = {  # NSEventType for the bridge
            "move": 5, "down": 1, "up": 2, "dragged": 6,
        }
        ns = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
            ns_type_map[kind], (0.0, 0.0), 0, 0.0, int(window_number), None, 0,
            int(click_count), 1.0)
        cg = ns.CGEvent()
        self._q.CGEventSetType(cg, type_map[kind])
        return cg

    def set_public_field(self, ev, field, value):
        self._q.CGEventSetIntegerValueField(ev, field, int(value))

    def set_private_field(self, ev, field, value):
        self._sky["SLEventSetIntegerValueField"](_as_ptr(ev), ctypes.c_uint32(field),
                                                 ctypes.c_int64(int(value)))

    def set_window_location(self, ev, pt):
        self._sky["CGEventSetWindowLocation"](_as_ptr(ev), _CGPoint(pt[0], pt[1]))

    def set_location(self, ev, pt):
        self._q.CGEventSetLocation(ev, (float(pt[0]), float(pt[1])))

    def set_source_user_data(self, ev, tag):
        self._q.CGEventSetIntegerValueField(ev, self._q.kCGEventSourceUserData, tag)

    def post(self, pid, ev):
        """[AMENDMENT] stamp a fresh uptime timestamp, then post to the target PID.
        Task 9's _post_one calls THIS (not SLEventPostToPid directly) so a fake port
        intercepts every post for ordering tests."""
        self._sky["CGEventSetTimestamp"](_as_ptr(ev), ctypes.c_uint64(time.monotonic_ns()))
        self._sky["SLEventPostToPid"](ctypes.c_int32(int(pid)), _as_ptr(ev))


def build_cg_event(port, kind, win_point, screen_point, click_count, pid, window_id):
    """Build + fully stamp one mouse CGEvent via the given port (real or fake).

    Stamps: the integer field table (public vs private setters), the private
    window-local location, the screen location, and our echo marker. Returns the
    event object the port created.
    """
    ev = port.make_event(kind, click_count, window_id)
    for field, value, via_private in mouse_event_fields(pid, window_id):
        (port.set_private_field if via_private else port.set_public_field)(ev, field, value)
    port.set_window_location(ev, (float(win_point[0]), float(win_point[1])))
    port.set_location(ev, (float(screen_point[0]), float(screen_point[1])))
    port.set_source_user_data(ev, SPIKE_EVENT_TAG)
    return ev


_SKY_CACHE = {}


def _skylight():
    """Lazily dlopen SkyLight + declare the private symbols per SKYLIGHT_SYMBOLS.

    Returns a dict name -> callable. Raises RuntimeError if a symbol is missing
    (recorded by the command body as a hard finding for this macOS version).
    """
    if _SKY_CACHE:
        return _SKY_CACHE
    _CTYPE = {
        "void": None, "uint32": ctypes.c_uint32, "int32": ctypes.c_int32,
        "uint64": ctypes.c_uint64, "int64": ctypes.c_int64,
        "pid": ctypes.c_int32, "ptr": ctypes.c_void_p, "cgpoint": _CGPoint,
    }
    sky = ctypes.CDLL("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight")
    out = {}
    for name, (restype, argtypes) in SKYLIGHT_SYMBOLS.items():
        try:
            fn = getattr(sky, name)
        except AttributeError as e:
            raise RuntimeError(f"SkyLight symbol {name} missing on this macOS") from e
        fn.restype = _CTYPE[restype]
        fn.argtypes = tuple(_CTYPE[a] for a in argtypes)
        out[name] = fn
    _SKY_CACHE.update(out)
    return _SKY_CACHE


def summarize_samples(samples: list) -> dict:
    """Aggregate samples taken DURING a post. Each sample is
    (frontmost_pid, cursor_x, cursor_y[, src_active, tgt_active, ax_focused_win]).
    Reports whether the real cursor moved, the frontmost app changed, or the
    source/target AppKit-active state flipped. Empty input is inconclusive (the
    sampler never ran / produced nothing)."""
    if not samples:
        return {"inconclusive": True, "frontmost_pids": [], "cursor_moved": False,
                "focus_changed": False, "isactive_changed": False,
                "cursor_x_range": None, "cursor_y_range": None,
                "ax_focused_windows": []}
    pids, xs, ys = [], [], []
    src_seen, tgt_seen, ax_wins = set(), set(), []
    for s in samples:
        fp, cx, cy = s[0], s[1], s[2]
        if fp not in pids:
            pids.append(fp)
        xs.append(cx)
        ys.append(cy)
        if len(s) > 3 and s[3] is not None:
            src_seen.add(s[3])
        if len(s) > 4 and s[4] is not None:
            tgt_seen.add(s[4])
        if len(s) > 5 and s[5] not in ax_wins:
            ax_wins.append(s[5])
    return {
        "inconclusive": False,
        "frontmost_pids": pids,
        "focus_changed": len(pids) > 1,
        "cursor_moved": (min(xs) != max(xs)) or (min(ys) != max(ys)),
        "cursor_x_range": (min(xs), max(xs)),
        "cursor_y_range": (min(ys), max(ys)),
        "isactive_changed": len(src_seen) > 1 or len(tgt_seen) > 1,
        "ax_focused_windows": ax_wins,
    }


class FocusCursorSampler:
    """Polls (on a daemon thread) the real cursor, the frontmost PID, the source/
    target apps' AppKit-active state, and the frontmost app's AX focused window,
    every `interval` s -- so a transient excursion during a zero/1ms post is not
    missed by before/after sampling alone. The probe fns are injectable for unit
    tests (the real ones use PyObjC lazily). A probe exception is swallowed so the
    thread keeps sampling. start() then stop() -> summarize_samples(self.samples)."""
    def __init__(self, source_pid=None, target_pid=None, interval=0.002,
                 ipc_interval=0.05, cursor_fn=None, frontmost_fn=None,
                 isactive_fn=None, ax_fn=None):
        self._src = source_pid
        self._tgt = target_pid
        self._interval = interval
        # The cheap cursor+frontmost probes run every tick; the expensive IPC
        # probes (isActive, AX) run on a coarser sub-cadence so the slow probe
        # does not govern the loop period (the sub-ms excursion the sampler exists
        # to catch must be sampled finely). Carried-forward between IPC ticks.
        self._ipc_every = max(1, round(ipc_interval / interval)) if interval else 1
        self._stop = threading.Event()
        self._t = None
        self.samples = []
        self._cursor_fn = cursor_fn or self._cursor
        self._frontmost_fn = frontmost_fn or self._frontmost_pid
        self._isactive_fn = isactive_fn or self._isactive
        self._ax_fn = ax_fn or self._ax_focused_window

    def _frontmost_pid(self):
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else -1

    def _cursor(self):
        Q = kb._quartz()
        loc = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return (float(loc.x), float(loc.y))

    def _isactive(self, pid):
        if pid is None:
            return None
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return bool(app.isActive()) if app is not None else None

    def _ax_focused_window(self, frontmost_pid):
        # best-effort: the AX focused window of the frontmost app; None if AX is
        # unavailable or (typical for an OpenGL surface) exposes nothing. Never raises.
        try:
            from ApplicationServices import (
                AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
                AXUIElementSetMessagingTimeout,
            )
            app = AXUIElementCreateApplication(frontmost_pid)
            # Bound the AX IPC so an unresponsive (mid-render) OpenGL app cannot
            # park the sampler thread on the ~6s default messaging timeout.
            AXUIElementSetMessagingTimeout(app, 0.05)
            err, win = AXUIElementCopyAttributeValue(app, "AXFocusedWindow", None)
            return None if err != 0 else repr(win)
        except Exception:
            return None

    def _run(self):
        tick = 0
        sa = ta = ax = None   # carried forward between IPC sub-cadence ticks
        while not self._stop.is_set():
            try:
                cx, cy = self._cursor_fn()
                fp = self._frontmost_fn()
                if tick % self._ipc_every == 0:
                    sa = self._isactive_fn(self._src)
                    ta = self._isactive_fn(self._tgt)
                    ax = self._ax_fn(fp)
                self.samples.append((fp, cx, cy, sa, ta, ax))
            except Exception:
                pass
            tick += 1
            time.sleep(self._interval)

    def start(self):
        if self._t is not None:
            raise RuntimeError("sampler already started")
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self, join_timeout=1.0):
        """Stop the thread and return the summary. `thread_stopped` is False if the
        worker did not exit within `join_timeout` (e.g. parked in a slow native
        probe) -- a signal the summary may be slightly truncated."""
        self._stop.set()
        alive_after = False
        if self._t is not None:
            self._t.join(timeout=join_timeout)
            alive_after = self._t.is_alive()
        out = summarize_samples(self.samples)
        out["thread_stopped"] = not alive_after
        return out


# ── delivery engine (native via injectable seams; orchestration unit-tested) ──
def _resolve_rec(pid):
    return next((r for r in kb.enumerate_windows() if r.pid == pid), None)


def _win_local(rec, frac, inset):
    """A content-relative fraction -> window-LOCAL pixel offset ((0,0)=content
    top-left). This is the point stamped via CGEventSetWindowLocation."""
    _, _, cw, ch = content_rect(rec.bounds, inset)
    return (frac[0] * cw, frac[1] * ch)


def _screen_point(rec, win_local, inset):
    """Window-local pixel offset -> global screen point for CGEventSetLocation."""
    cx, cy, _, _ = content_rect(rec.bounds, inset)
    return (cx + win_local[0], cy + win_local[1])


def _post_one(port, pid, window_id, rec, inset, spec):
    """Build + post a single EventSpec THROUGH port.post (so a fake port intercepts
    it). Primer events post off-window at OFF_WINDOW_POINT for both points."""
    if spec.primer:
        win_pt = screen_pt = OFF_WINDOW_POINT
    else:
        win_pt = spec.point
        screen_pt = _screen_point(rec, spec.point, inset)
    ev = build_cg_event(port, spec.kind, win_pt, screen_pt, spec.click_count,
                        pid, window_id)
    port.post(pid, ev)


def _gap_after(spec, gaps, hold):
    if spec.kind == "move":
        return gaps["after_move"]
    if spec.kind == "down":
        return gaps["primer_internal"] if spec.primer else gaps["down_to_up"] + hold
    if spec.kind == "up":
        return gaps["primer_to_target"] if spec.primer else 0.0
    return 0.0  # dragged: rely on --timing/observation; no inter-step sleep


# native PSN/window accessors (wrapped so _resolve_psns is seam-testable) ──────
def _native_main_cid():
    return _skylight()["CGSMainConnectionID"]()


def _native_window_owner(cid, window_id):
    sky = _skylight()
    owner = ctypes.c_uint32(0)
    err = sky["SLSGetWindowOwner"](ctypes.c_uint32(int(cid)),
                                   ctypes.c_uint32(int(window_id)), ctypes.byref(owner))
    return (int(err), int(owner.value))


def _native_connection_psn(owner_cid):
    sky = _skylight()
    psn = (ctypes.c_uint32 * 2)()
    err = sky["SLSGetConnectionPSN"](ctypes.c_uint32(int(owner_cid)), ctypes.byref(psn))
    return (int(err), bytes(psn))


def _native_front_psn():
    sky = _skylight()
    prev = (ctypes.c_uint32 * 2)()
    err = sky["_SLPSGetFrontProcess"](ctypes.byref(prev))
    if err != 0:
        raise RuntimeError(f"_SLPSGetFrontProcess failed: status={err}")
    return bytes(prev)


def _native_frontmost_pid():
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app is not None else None


def _native_window_list():
    import Quartz
    return Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []


def _native_focus_post(psn_bytes, record_bytes):
    err = _skylight()["SLPSPostEventRecordTo"](psn_bytes, record_bytes)
    if err != 0:
        raise RuntimeError(f"SLPSPostEventRecordTo failed: status={err}")


def _resolve_psns(window_id, *, main_cid_fn=None, owner_fn=None, psn_fn=None,
                  front_psn_fn=None, front_pid_fn=None):
    """Resolve (target_psn_bytes, prev_frontmost_psn_bytes, prev_frontmost_pid) for
    the focus record. The accessor fns are injectable for tests; defaults wrap the
    native ctypes calls. Raises RuntimeError on a non-zero SkyLight status."""
    main_cid_fn = main_cid_fn or _native_main_cid
    owner_fn = owner_fn or _native_window_owner
    psn_fn = psn_fn or _native_connection_psn
    front_psn_fn = front_psn_fn or _native_front_psn
    front_pid_fn = front_pid_fn or _native_frontmost_pid
    cid = main_cid_fn()
    err, owner = owner_fn(cid, window_id)
    if err != 0:
        raise RuntimeError(f"SLSGetWindowOwner failed: status={err}")
    err, target_psn = psn_fn(owner)
    if err != 0:
        raise RuntimeError(f"SLSGetConnectionPSN failed: status={err}")
    return (target_psn, front_psn_fn(), front_pid_fn())


def _front_window_id(pid, *, window_list_fn=None):
    """The frontmost on-screen window id owned by `pid`, or None -- the prior key
    window to restore. `window_list_fn` injectable for tests."""
    window_list_fn = window_list_fn or _native_window_list
    if pid is None:
        return None
    for w in window_list_fn():
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowNumber"):
            return int(w["kCGWindowNumber"])
    return None


def _apply_focus(window_id, *, resolve_psns_fn=None, front_window_fn=None,
                 sky_post=None, sleep=None):
    """focus-without-raise: defocus the prior frontmost, focus the target window.
    Returns a restore-context dict for _restore_focus. Spec 2.2. Seams injectable.

    Transactional: if focusing the target fails AFTER the prior app was already
    defocused, the prior app is re-focused before the error propagates, so a partial
    failure never strands the prior app defocused."""
    resolve_psns_fn = resolve_psns_fn or (lambda: _resolve_psns(window_id))
    front_window_fn = front_window_fn or _front_window_id
    sky_post = sky_post or _native_focus_post
    _sleep = sleep or time.sleep
    target_psn, prev_psn, prev_pid = resolve_psns_fn()
    prev_window_id = front_window_fn(prev_pid) if prev_pid is not None else None
    if prev_psn is not None:
        sky_post(prev_psn, build_focus_record(window_id, mode=0x02))
    try:
        sky_post(target_psn, build_focus_record(window_id, mode=0x01))
    except Exception:
        # roll back the prior-app defocus so we don't leave it stranded
        if prev_psn is not None and prev_window_id is not None:
            try:
                sky_post(prev_psn, build_focus_record(prev_window_id, mode=0x01))
            except Exception:
                pass
        raise
    _sleep(0.05)
    return {"prev_psn": prev_psn, "prev_window_id": prev_window_id,
            "target_psn": target_psn, "target_window_id": window_id}


def _restore_focus(ctx, *, sky_post=None, sleep=None, settle=0.0):
    """Invert _apply_focus: defocus the target, re-focus the prior window. Best-effort
    if the prior focused window id was unresolved (None). BOTH posts are attempted
    even if the first fails (so a target-defocus failure never skips re-focusing the
    prior window); if any post failed, the error is raised AFTER both are attempted,
    so _deliver_specs surfaces it in the summary rather than swallowing it."""
    sky_post = sky_post or _native_focus_post
    err = None
    if ctx.get("target_psn") is not None:
        try:
            sky_post(ctx["target_psn"], build_focus_record(ctx["target_window_id"], mode=0x02))
        except Exception as e:
            err = e
    pw = ctx.get("prev_window_id")
    if ctx.get("prev_psn") is not None and pw is not None:
        try:
            sky_post(ctx["prev_psn"], build_focus_record(pw, mode=0x01))
        except Exception as e:
            err = e
    if settle and sleep:
        sleep(settle)
    if err is not None:
        raise err


def _deliver_specs(pid, window_id, rec, inset, specs, opts, *,
                   port=None, sleep=None, apply_focus=None, restore_focus=None,
                   make_sampler=None):
    """Post a spec list with concurrent sampler instrumentation, optional
    focus-without-raise (+ restore), and per-spec timing. Returns the sampler
    summary. Best-effort: a native failure DURING focus or delivery (or during
    restore) is caught -- the focus is restored if it was applied, the sampler is
    always stopped, and the failure is surfaced as `summary['error']` with
    `inconclusive` set; this never raises through for focus/delivery/restore. (A
    SETUP failure -- missing SkyLight symbol, or the sampler thread failing to
    start -- surfaces as an exception by design, so a broken environment is loud.)
    The keyword seams (port, sleep, apply_focus, restore_focus, make_sampler) are
    for unit tests; the live path builds the real ones. When no port seam is given,
    the Accessibility preflight gates delivery."""
    if port is None and not kb.preflight_post_access():
        print("  REFUSED: grant Accessibility/Input Monitoring; aborting.")
        return {"inconclusive": True}
    port = port or _SkyPort(kb._quartz(), _skylight())
    _sleep = sleep or time.sleep
    _apply = apply_focus or _apply_focus
    _restore = restore_focus or _restore_focus
    make_sampler = make_sampler or (lambda: FocusCursorSampler(target_pid=pid))
    sampler = make_sampler()
    sampler.start()
    focus_ctx = None
    error = None
    try:
        try:
            if opts.focus:
                focus_ctx = _apply(window_id)
            gaps = timing_gaps(opts.timing, has_primer=opts.primer)
            for spec in specs:
                _post_one(port, pid, window_id, rec, inset, spec)
                _sleep(_gap_after(spec, gaps, opts.hold))
        except Exception as e:
            # A native focus/delivery failure must not crash the operator run; it
            # also must not skip restoring a focus we already stole.
            error = f"{type(e).__name__}: {e}"
            print(f"  ERROR during delivery: {error}")
        finally:
            if opts.restore_focus and focus_ctx is not None:
                try:
                    _restore(focus_ctx)
                except Exception as e:
                    restore_err = f"restore failed: {type(e).__name__}: {e}"
                    print(f"  ERROR during focus restore: {restore_err}")
                    if error is None:
                        error = restore_err
    finally:
        summary = sampler.stop()
    if error is not None:
        summary["inconclusive"] = True
        summary["error"] = error
    return summary


def cmd_list(rest):
    # One enumeration source across all spikes.
    return kb.cmd_list(rest)


def cmd_probe_rect(rest):
    # The mouse spike's content-rect calibration is platform-identical; reuse it.
    return ms.cmd_probe_rect(rest)


def _all_int(positionals):
    """True if every positional actually parses with int(), so a command rejects a
    non-numeric pid/window_id with usage + 2 instead of crashing. Uses int() itself
    (not str.isdigit(), which is Unicode-aware and accepts e.g. superscript digits
    that int() then rejects), so nothing int() refuses can slip past this guard."""
    try:
        for p in positionals:
            int(p)
        return True
    except (ValueError, TypeError):
        return False


def cmd_sl_click(rest):
    try:
        opts = parse_sl_args(rest)
    except ArgError as e:
        print(f"usage: sl-click <pid> <window_id> [flags]; {e}")
        return 2
    if len(opts.positionals) != 2 or not _all_int(opts.positionals):
        print("usage: sl-click <pid> <window_id> [--focus] [--primer] "
              "[--restore-focus] [--timing P] [--inset N] [--frac FX FY] "
              "[--hold S] [--reps N]")
        return 2
    pid, window_id = int(opts.positionals[0]), int(opts.positionals[1])
    rec = _resolve_rec(pid)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    win_pt = _win_local(rec, opts.frac, opts.inset)
    specs = click_event_specs(win_pt, primer=opts.primer)
    print(f"[sl-click] pid={pid} wid={window_id} focus={opts.focus} "
          f"primer={opts.primer} timing={opts.timing} frac={opts.frac} reps={opts.reps}")
    print("  put the SOURCE toon FOREGROUND and the TARGET toon BACKGROUND;")
    print("  hold movement in the source. Watch: does the TARGET register the click")
    print("  at the right spot? does the source/cursor/focus stay put?")
    input("  press Enter when positioned... ")
    last = {}
    for _ in range(opts.reps):
        last = _deliver_specs(pid, window_id, rec, opts.inset, specs, opts)
    print(f"  sampler(last rep): {last}")
    print("  record: registered? (N/reps), position correct?, focus/cursor changed?")
    return 0


def cmd_sl_gesture(rest):
    try:
        opts = parse_sl_args(rest)
    except ArgError as e:
        print(f"usage: sl-gesture <pid> <window_id> --kind drag|hover [flags]; {e}")
        return 2
    if len(opts.positionals) != 2 or opts.kind is None or not _all_int(opts.positionals):
        print("usage: sl-gesture <pid> <window_id> --kind drag|hover "
              "[--from FX FY] [--to FX FY] [--inset N] [--timing P] [--reps N]")
        return 2
    pid, window_id = int(opts.positionals[0]), int(opts.positionals[1])
    rec = _resolve_rec(pid)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    if opts.kind == "hover":
        pts = [_win_local(rec, (opts.frm[0] + (opts.to[0] - opts.frm[0]) * t,
                                opts.frm[1] + (opts.to[1] - opts.frm[1]) * t),
                          opts.inset) for t in (0.0, 0.5, 1.0)]
        specs = hover_event_specs(pts)
    else:
        frm = _win_local(rec, opts.frm, opts.inset)
        to = _win_local(rec, opts.to, opts.inset)
        specs = drag_event_specs(frm, to, steps=4)
    print(f"[sl-gesture] pid={pid} wid={window_id} kind={opts.kind} "
          f"from={opts.frm} to={opts.to} timing={opts.timing}")
    print("  TARGET toon BACKGROUND. Watch the cursor/selection TRACK the path; "
          "check start, two mid points, and the end.")
    input("  press Enter when positioned... ")
    last = {}
    for _ in range(opts.reps):
        last = _deliver_specs(pid, window_id, rec, opts.inset, specs, opts)
    print(f"  sampler(last rep): {last}")
    print("  record: tracked at every sampled point? side effects?")
    return 0


def cmd_sl_fanout(rest):
    try:
        opts = parse_sl_args(rest)
    except ArgError as e:
        print(f"usage: sl-fanout <pidA> <widA> <pidB> <widB> [flags]; {e}")
        return 2
    if (len(opts.positionals) < 4 or len(opts.positionals) % 2 != 0
            or not _all_int(opts.positionals)):
        print("usage: sl-fanout <pidA> <widA> <pidB> <widB> [...] "
              "[--frac FX FY] [--timing P] [--reps N]  (a neutral app must be FRONT)")
        return 2
    pairs = [(int(opts.positionals[i]), int(opts.positionals[i + 1]))
             for i in range(0, len(opts.positionals), 2)]
    recs = {}
    for pid, wid in pairs:
        rec = _resolve_rec(pid)
        if rec is None:
            print(f"pid={pid} is not a current TTR window.")
            return 1
        recs[pid] = (wid, rec)
    if not kb.preflight_post_access():
        print("  REFUSED: grant Accessibility/Input Monitoring; aborting.")
        return 1
    print(f"[sl-fanout] targets={[p for p, _ in pairs]} timing={opts.timing} "
          f"frac={opts.frac} reps={opts.reps}")
    print("  bring a NEUTRAL app (Terminal/Finder) FRONT so BOTH toons are background.")
    print("  watch BOTH toons register the click; note any added lag with 2 vs 1.")
    input("  press Enter when a neutral app is frontmost... ")
    port = _SkyPort(kb._quartz(), _skylight())
    gaps = timing_gaps(opts.timing, has_primer=False)
    points = {pid: _win_local(rec, opts.frac, opts.inset)
              for pid, (wid, rec) in recs.items()}
    target_ids = [pid for pid, _ in pairs]
    for rep in range(opts.reps):
        sampler = FocusCursorSampler()
        sampler.start()
        plan = fanout_phase_plan(target_ids, (0.0, 0.0))  # ordering only
        prev_phase, phase_t0, phase_ms = None, time.monotonic(), {}
        try:
            # phase-wise: pay the gap + record the elapsed ONCE per phase boundary.
            for phase, tid, spec in plan:
                if prev_phase is not None and phase != prev_phase:
                    phase_ms[prev_phase] = round((time.monotonic() - phase_t0) * 1000, 2)
                    time.sleep(gaps["after_move"] if prev_phase == "move"
                               else gaps["down_to_up"])
                    phase_t0 = time.monotonic()
                wid, rec = recs[tid]
                _post_one(port, tid, wid, rec, opts.inset,
                          EventSpec(spec.kind, points[tid], spec.click_count))
                prev_phase = phase
            if prev_phase is not None:
                phase_ms[prev_phase] = round((time.monotonic() - phase_t0) * 1000, 2)
        finally:
            summary = sampler.stop()
        print(f"  rep {rep + 1}/{opts.reps}: per-phase ms={phase_ms} "
              f"for {len(target_ids)} targets; sampler: {summary}")
    print("  record: both registered? per-target correct? per-phase latency acceptable?")
    return 0


def cmd_sl_positive_control(rest):
    try:
        opts = parse_sl_args(rest)
    except ArgError as e:
        print(f"usage: sl-positive-control <fg_pid> <window_id> [--frac FX FY]; {e}")
        return 2
    if len(opts.positionals) != 2 or not _all_int(opts.positionals):
        print("usage: sl-positive-control <fg_pid> <window_id> [--frac FX FY]")
        return 2
    pid, window_id = int(opts.positionals[0]), int(opts.positionals[1])
    rec = _resolve_rec(pid)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    win_pt = _win_local(rec, opts.frac, opts.inset)
    specs = click_event_specs(win_pt, primer=False)
    print(f"[sl-positive-control] FORCES the SkyLight path to the FOREGROUND key "
          f"window pid={pid}. This validates event CONSTRUCTION only (diagnostic):")
    print("  a foreground failure can coexist with background success (cua routes "
          "frontmost via HID). Bring this toon to the FRONT.")
    input("  press Enter when it is frontmost... ")
    summary = _deliver_specs(pid, window_id, rec, opts.inset, specs, opts)
    print(f"  sampler: {summary}")
    print("  record: did the foreground toon register it? (diagnostic, not a gate)")
    return 0


def cmd_sl_echo(rest):
    """Does SPIKE_EVENT_TAG survive SLEventPostToPid? Posts 10 tagged moves through
    the SkyLight path while a listen-only tap classifies ours vs foreign (spec
    3.1 echo guard / 4.1 criterion 7). The tap scaffold mirrors
    scripts/macos_mouse_spike.py cmd_echo; only the POST path differs."""
    usage = "usage: sl-echo <pid> <window_id> [--seconds N] [--inset N]"
    try:
        pos, opts = kb._parse_opts(rest, {"seconds": (int, 15), "inset": (int, 0)})
    except (ValueError, SystemExit):   # bad option value / unknown flag -> usage, not a crash
        print(usage)
        return 2
    if len(pos) != 2 or not _all_int(pos):
        print(usage)
        return 2
    pid, window_id = int(pos[0]), int(pos[1])
    rec = _resolve_rec(pid)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    if not kb.preflight_listen_access():
        print("No listen access; grant Input Monitoring to your terminal/python.")
        return 1
    Q = kb._quartz()
    import Quartz as _Q

    stats = {"tapped": 0, "ours": 0, "foreign": 0, "tap_disabled": 0}
    mask = ((1 << Q.kCGEventMouseMoved) | (1 << Q.kCGEventLeftMouseDown)
            | (1 << Q.kCGEventLeftMouseUp))

    def _cb(proxy, etype, event, refcon):
        if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
            stats["tap_disabled"] += 1
            Q.CGEventTapEnable(tap, True)
            return event
        stats["tapped"] += 1
        ud = Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData)
        stats["ours" if kb.is_spike_event(ud) else "foreign"] += 1
        return event

    tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap,
                             Q.kCGEventTapOptionListenOnly, mask, _cb, None)
    if not tap:
        print("  ERROR: could not create the listen-only tap (Input Monitoring?).")
        return 1
    src = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
    holder, ready = {}, threading.Event()

    def _run():
        rl = _Q.CFRunLoopGetCurrent()
        holder["rl"] = rl
        _Q.CFRunLoopAddSource(rl, src, _Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(tap, True)
        ready.set()
        _Q.CFRunLoopRun()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if not ready.wait(timeout=2.0):
        print("  ERROR: tap thread not ready within 2s.")
        return 1
    time.sleep(0.1)

    port = _SkyPort(Q, _skylight())
    win_pt = _win_local(rec, (0.5, 0.5), opts["inset"])
    print(f"[sl-echo] posting 10 SkyLight-tagged moves to pid={pid}; tap is listen-only.")
    for i in range(10):
        _post_one(port, pid, window_id, rec, opts["inset"],
                  EventSpec("move", (win_pt[0] + i, win_pt[1]), 0))
        time.sleep(0.05)
    print(f"[sl-echo] now move your REAL mouse ~{opts['seconds']}s so the tap sees "
          "physical input too.")
    time.sleep(opts["seconds"])
    rl = holder.get("rl")
    if rl is not None:
        _Q.CFRunLoopStop(rl)
    t.join(timeout=1.0)
    print(f"[sl-echo] {stats}")
    print("  ours>0 (the ONLY unambiguous signal) => the SkyLight-posted event RE-ENTERS "
          "this session tap AND carries SPIKE_EVENT_TAG: production capture can de-dup on "
          "the marker. ours==0 is AMBIGUOUS: either the marker was stripped, OR "
          "SLEventPostToPid delivery simply does not re-enter a session tap at all (a "
          "different path than the CGEventPostToPid the sibling echo exercised) -- so "
          "production may still need a timing/held-state de-dup; record WHICH, do not "
          "assume 'marker lost'. foreign>0 confirms the tap is alive on physical input "
          "(control; free-MOVE the mouse, since the mask omits dragged events).")
    return 0


def parse_codesign_flags(codesign_output: str, entitlements: str = "") -> dict:
    """Pull the injection-relevant barriers out of `codesign -dvvv` text (and, when
    given, the `codesign -d --entitlements` blob). Real `-dvvv` encodes hardened
    runtime + library validation as TOKENS inside `flags=0x..(...)` (`runtime`,
    `library-validation`); get-task-allow is an ENTITLEMENT, present only in the
    entitlements blob, never in `-dvvv`."""
    import re
    text = codesign_output.lower()
    return {
        "hardened_runtime": "runtime" in text and "flags=" in text,
        "library_validation": "library-validation" in text,
        # the get-task-allow KEY must be immediately followed by <true/> -- not merely
        # present alongside some other true entitlement.
        "get_task_allow": bool(re.search(
            r"get-task-allow\s*</key>\s*<true\s*/?>", entitlements, re.I)),
    }


def timeslice_sequence(kind, frm, mid, to, center):
    """The ordered (event_kind_name, point) GLOBAL posts for a timeslice gesture.
    Pure (no Quartz) so the click-vs-drag contract is unit-testable: click = a
    down/up at `center`; drag = move->down->dragged->dragged->up across frm/mid/to."""
    if kind == "drag":
        return [("move", frm), ("down", frm), ("dragged", mid),
                ("dragged", to), ("up", to)]
    return [("down", center), ("up", center)]


def _task_for_pid_probe(pid):
    """Attempt task_for_pid(self, pid) and return the mach kern_return (0 = got the
    task port -> live injection feasible; non-zero = blocked, the usual case without
    SIP-off + root or a get-task-allow entitlement). Native; live-only."""
    libc = ctypes.CDLL(None)
    self_task = ctypes.c_uint.in_dll(libc, "mach_task_self_").value
    libc.task_for_pid.restype = ctypes.c_int
    out = ctypes.c_uint(0)
    return int(libc.task_for_pid(ctypes.c_uint(self_task), ctypes.c_int(int(pid)),
                                 ctypes.byref(out)))


def cmd_timeslice(rest, kind="click"):
    usage = "usage: timeslice-click|timeslice-drag <pidA> <pidB> [--inset N]"
    try:
        pos, opts = kb._parse_opts(rest, {"inset": (int, 0)})
    except (ValueError, SystemExit):
        print(usage)
        return 2
    if len(pos) != 2 or not _all_int(pos):
        print(usage)
        return 2
    pidA, pidB = int(pos[0]), int(pos[1])
    if pidA == pidB:
        print("pidA and pidB must differ.")
        return 2
    recs = {r.pid: r for r in kb.enumerate_windows()}
    if pidA not in recs or pidB not in recs:
        print(f"both pids must be TTR windows; found {sorted(recs)}")
        return 1
    if not kb.preflight_post_access():
        print("  REFUSED: grant Accessibility (post-event access); aborting "
              "(otherwise the raise/restore happen but nothing clicks -- a silent no-op).")
        return 1
    Q = kb._quartz()
    b = recs[pidB]
    inset = opts["inset"]
    print(f"[timeslice-{kind}] DEGRADED-FALLBACK rung: keep pid={pidA} FRONT; this will "
          f"briefly raise pid={pidB}, GLOBAL-{kind} it, and restore.")
    print("  watch for: focus flicker, the REAL cursor jumping, the source toon "
          "losing focus. This rung CANNOT preserve cursor/focus by design.")
    input("  press Enter when pidA is frontmost... ")
    from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
    saved = Q.CGEventGetLocation(Q.CGEventCreate(None))
    appB = NSRunningApplication.runningApplicationWithProcessIdentifier_(pidB)
    appA = NSRunningApplication.runningApplicationWithProcessIdentifier_(pidA)
    if appB is None or appA is None:
        print("  could not resolve NSRunningApplication for both pids.")
        return 1
    appB.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.05)
    name_to_type = {"move": Q.kCGEventMouseMoved, "down": Q.kCGEventLeftMouseDown,
                    "dragged": Q.kCGEventLeftMouseDragged, "up": Q.kCGEventLeftMouseUp}
    seq = timeslice_sequence(
        kind,
        content_point_to_global((0.3, 0.5), b.bounds, inset),
        content_point_to_global((0.5, 0.5), b.bounds, inset),
        content_point_to_global((0.7, 0.5), b.bounds, inset),
        content_point_to_global((0.5, 0.5), b.bounds, inset))
    try:
        for kname, pt in seq:
            ev = Q.CGEventCreateMouseEvent(None, name_to_type[kname], pt,
                                           Q.kCGMouseButtonLeft)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
    finally:
        # always restore the foreground app + the real cursor, even on a mid-post error
        time.sleep(0.05)
        appA.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        warp = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (saved.x, saved.y), 0)
        Q.CGEventPost(Q.kCGHIDEventTap, warp)
    print(f"  record (DEGRADED schema): the {kind} landed on pidB? how disruptive was "
          f"the flicker/focus/cursor? "
          f"{'did the drag track?' if kind == 'drag' else '(hover not attemptable this way)'}")
    return 0


def cmd_inject_preflight(rest):
    usage = "usage: inject-preflight <pid>"
    try:
        pos, _opts = kb._parse_opts(rest, {})
    except (ValueError, SystemExit):
        print(usage)
        return 2
    if len(pos) != 1 or not _all_int(pos):
        print(usage)
        return 2
    pid = int(pos[0])
    rec = next((r for r in kb.enumerate_windows() if r.pid == pid), None)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    import subprocess
    try:
        import psutil
        exe = psutil.Process(pid).exe()
    except Exception as e:
        print(f"  could not resolve executable path: {e}")
        return 1
    print(f"[inject-preflight] pid={pid} exe={exe} (BARRIER report only; no hook).")
    try:
        cs = subprocess.run(["codesign", "-dvvv", exe], capture_output=True,
                            text=True, timeout=10)
        cs_text = (cs.stdout or "") + (cs.stderr or "")
    except Exception as e:
        cs_text = f"(codesign failed: {e})"
    try:
        ent = subprocess.run(["codesign", "-d", "--entitlements", ":-", exe],
                             capture_output=True, text=True, timeout=10).stdout or ""
    except Exception as e:
        ent = f"(entitlements failed: {e})"
    flags = parse_codesign_flags(cs_text, ent)
    try:
        r = subprocess.run(["lipo", "-archs", exe], capture_output=True,
                           text=True, timeout=10)
        arch = r.stdout.strip()
        if r.returncode != 0 or not arch:   # any failure -> use the fallback
            raise RuntimeError(r.stderr.strip() or f"lipo exit {r.returncode}")
    except Exception:
        import platform
        arch = platform.machine()   # host-arch fallback when lipo is unavailable/fails
    try:
        kr = _task_for_pid_probe(pid)
        tfp = (f"kern_return={kr} "
               f"({'GOT task port (live injection feasible)' if kr == 0 else 'blocked'})")
    except Exception as e:
        tfp = f"(probe failed: {type(e).__name__}: {e})"
    print(f"  codesign barriers: {flags}")
    print(f"  arch: {arch}")
    print(f"  task_for_pid (live Mach injection): {tfp}")
    print(f"  raw codesign -dvvv (verify the parse): {cs_text.strip()[:400]}")
    print("  DYLD_INSERT_LIBRARIES is LAUNCH-time (needs relaunch + no library "
          "validation + a non-hardened or self-signed binary); task_for_pid is LIVE "
          "(needs get-task-allow OR SIP-off + root). A TRUE feasibility check needs a "
          "no-op dylib that signals back; this reports BARRIERS only. Record the "
          "codesign flags, arch, and the task_for_pid kern_return as the rung-3 sizing.")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "timeslice-click":
        return cmd_timeslice(rest, kind="click")
    if cmd == "timeslice-drag":
        return cmd_timeslice(rest, kind="drag")
    dispatch = {
        "list": cmd_list,
        "probe-rect": cmd_probe_rect,
        "sl-click": cmd_sl_click,
        "sl-gesture": cmd_sl_gesture,
        "sl-fanout": cmd_sl_fanout,
        "sl-positive-control": cmd_sl_positive_control,
        "sl-echo": cmd_sl_echo,
        "inject-preflight": cmd_inject_preflight,
    }
    fn = dispatch.get(cmd)
    if fn is None:
        print(__doc__)
        return 2
    return fn(rest)


if __name__ == "__main__":
    raise SystemExit(main())
