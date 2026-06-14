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

    def stop(self):
        """Stop the thread and return the summary. `thread_stopped` is False if the
        worker did not exit within the join window (e.g. parked in a slow native
        probe) -- a signal the summary may be slightly truncated."""
        self._stop.set()
        alive_after = False
        if self._t is not None:
            self._t.join(timeout=1.0)
            alive_after = self._t.is_alive()
        out = summarize_samples(self.samples)
        out["thread_stopped"] = not alive_after
        return out


def cmd_list(rest):
    # One enumeration source across all spikes.
    return kb.cmd_list(rest)


def cmd_probe_rect(rest):
    # The mouse spike's content-rect calibration is platform-identical; reuse it.
    return ms.cmd_probe_rect(rest)


def cmd_sl_click(rest):
    print("cmd_sl_click: implemented in Task 9")
    return 2


def cmd_sl_gesture(rest):
    print("cmd_sl_gesture: implemented in Task 9")
    return 2


def cmd_sl_fanout(rest):
    print("cmd_sl_fanout: implemented in Task 9")
    return 2


def cmd_sl_positive_control(rest):
    print("cmd_sl_positive_control: implemented in Task 9")
    return 2


def cmd_sl_echo(rest):
    print("cmd_sl_echo: implemented in Task 10")
    return 2


def cmd_timeslice(rest):
    print("cmd_timeslice: implemented in Task 10")
    return 2


def cmd_inject_preflight(rest):
    print("cmd_inject_preflight: implemented in Task 10")
    return 2


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    dispatch = {
        "list": cmd_list,
        "probe-rect": cmd_probe_rect,
        "sl-click": cmd_sl_click,
        "sl-gesture": cmd_sl_gesture,
        "sl-fanout": cmd_sl_fanout,
        "sl-positive-control": cmd_sl_positive_control,
        "sl-echo": cmd_sl_echo,
        "timeslice-click": cmd_timeslice,
        "timeslice-drag": cmd_timeslice,
        "inject-preflight": cmd_inject_preflight,
    }
    fn = dispatch.get(cmd)
    if fn is None:
        print(__doc__)
        return 2
    return fn(rest)


if __name__ == "__main__":
    raise SystemExit(main())
