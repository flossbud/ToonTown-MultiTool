#!/usr/bin/env python3
"""macOS mouse-forwarding feasibility spike (Phase 0). Standalone operator probe.

Gates (see docs/superpowers/specs/2026-06-13-macos-click-sync-port-design.md S2):
  delivery  - background CGEventPostToPid of click/move/drag to an UNFOCUSED TTR PID
  content   - the content-rect (drawable) vs kCGWindowBounds (frame) transform
  coords    - global points / top-left, incl. Retina + a second display
  echo      - does a posted event re-enter a listen-only session tap; marker survives
  motion    - try-hard hover (mouseMoved) + drag (leftMouseDragged): plain/carrier/AX

Usage:
  python3 scripts/macos_mouse_spike.py list
  python3 scripts/macos_mouse_spike.py probe-rect <pid> [--inset 0]
  python3 scripts/macos_mouse_spike.py click <pidA> <pidB> [--inset 0]
  python3 scripts/macos_mouse_spike.py motion <pid> [--kind hover|drag]
        [--mode plain|carrier|ax] [--inset 0] [--steps 40]
  python3 scripts/macos_mouse_spike.py echo [--seconds 20] [--pid PID] [--inset 0]

PyObjC is imported lazily inside the harness so this file imports on any platform
(the pure-logic helpers below are unit-tested on Linux/Windows CI). Window
enumeration + preflight + event-source helpers are reused from the keyboard spike
(scripts/macos_input_spike.py) so both spikes share one TTR session and never
diverge on enumeration.
"""
from __future__ import annotations

import os
import sys
import time

# Reuse the keyboard spike's tested helpers (sibling script in this dir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macos_input_spike as kb  # noqa: E402  (path insert must precede import)

# Same marker as the keyboard spike so a mixed session stays consistent.
SPIKE_EVENT_TAG = kb.SPIKE_EVENT_TAG


def content_rect(frame_bounds, inset_top=0):
    """Frame (kCGWindowBounds, global top-left points) -> drawable/content rect.

    Subtracts a top inset (the title bar). A borderless/fullscreen window has
    inset_top == 0. Height clamps at 0, never negative.
    """
    x, y, w, h = frame_bounds
    return (x, y + inset_top, w, max(0, h - inset_top))


def content_point_to_global(frac_xy, frame_bounds, inset_top=0):
    """A content-relative fraction (fx, fy) in [0,1] -> global (x, y) point.

    (0,0) is the content top-left, (1,1) the bottom-right. Floats; callers round
    only at the CGEvent boundary.
    """
    cx, cy, cw, ch = content_rect(frame_bounds, inset_top)
    fx, fy = frac_xy
    return (cx + fx * cw, cy + fy * ch)


def classify_tapped(user_data) -> str:
    """A tapped event's kCGEventSourceUserData -> 'ours' | 'foreign'."""
    return "ours" if kb.is_spike_event(user_data) else "foreign"


def post_mouse(pid, window_id, etype, global_x, global_y, button=None,
               source=None, state_name="combined", expected_bundle="__unset__",
               revalidate=True) -> bool:
    """Post one mouse event to `pid` at a GLOBAL point, tagged for echo detection.

    Returns False (never raises) if access is missing or the target failed
    re-validation. `revalidate=False` skips the per-call enumeration for hot
    paths (motion sweeps); the Accessibility preflight is ALWAYS checked.
    """
    Q = kb._quartz()
    if not kb.preflight_post_access():
        print("  REFUSED: no post-event access (grant Accessibility)")
        return False
    if revalidate and not kb.pid_alive_and_ttr(pid, window_id, expected_bundle):
        print(f"  REFUSED: target pid={pid} window_id={window_id} no longer valid")
        return False
    if button is None:
        button = Q.kCGMouseButtonLeft
    src = source if source is not None else kb._event_source(state_name)
    ev = Q.CGEventCreateMouseEvent(src, etype, (float(global_x), float(global_y)), button)
    Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, SPIKE_EVENT_TAG)
    Q.CGEventPostToPid(pid, ev)
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    dispatch = {
        "list": cmd_list,
        "probe-rect": cmd_probe_rect,
        "click": cmd_click,
        "motion": cmd_motion,
        "echo": cmd_echo,
    }
    fn = dispatch.get(cmd)
    if fn is None:
        print(__doc__)
        return 2
    return fn(rest)


# Command bodies are added by Tasks 2-5; defined here so main() routing is
# testable in isolation (each is monkeypatched in the routing test).
def cmd_list(rest):
    # The keyboard spike's list already prints preflight + TTR windows; reuse it
    # verbatim so the operator has one enumeration source across both spikes.
    return kb.cmd_list(rest)


def _click_at(pid, wid, frac, inset, bundle, hold=0.05):
    """Post a left down, hold for `hold`s, then up, at a content-relative point.

    A longer `hold` lets the operator observe the DOWN state (button press /
    hover-highlight) separately from the UP (release/activation), so the spec's
    'judge leftMouseDown and leftMouseUp separately' is operator-observable.
    Returns the refused-post count (0, 1, or 2).
    """
    Q = kb._quartz()
    recs = {r.pid: r for r in kb.enumerate_windows()}
    rec = recs.get(pid)
    if rec is None:
        print(f"  REFUSED: pid={pid} not a current TTR window")
        return 1
    gx, gy = content_point_to_global(frac, rec.bounds, inset)
    refused = 0
    try:
        if not post_mouse(pid, wid, Q.kCGEventLeftMouseDown, gx, gy,
                          expected_bundle=bundle):
            refused += 1
        time.sleep(hold)
    finally:
        # Always release, even on an interrupt during the down or the hold, so
        # the target is never left with an unmatched mouse-down (mirrors the
        # keyboard spike's _hold: down + sleep in try, up in finally).
        if not post_mouse(pid, wid, Q.kCGEventLeftMouseUp, gx, gy,
                          expected_bundle=bundle):
            refused += 1
    return refused


def cmd_probe_rect(rest):
    pos, opts = kb._parse_opts(rest, {"inset": (int, 0)})
    if len(pos) != 1:
        print("usage: probe-rect <pid> [--inset 0]")
        return 2
    pid = int(pos[0])
    rec = next((r for r in kb.enumerate_windows() if r.pid == pid), None)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    inset = opts["inset"]
    print(f"[content] frame={rec.bounds} inset_top={inset} -> "
          f"content={content_rect(rec.bounds, inset)}")
    print("  bring this toon to the FRONT so you can see where each click lands.")
    input("  press Enter when it is frontmost... ")
    refused = 0
    corners = [("top-left", (0.02, 0.02)), ("top-right", (0.98, 0.02)),
               ("bottom-left", (0.02, 0.98)), ("bottom-right", (0.98, 0.98)),
               ("center", (0.5, 0.5))]
    for name, frac in corners:
        print(f"  clicking {name} (frac={frac}); watch where the in-game cursor lands.")
        refused += _click_at(pid, rec.window_id, frac, inset, rec.bundle_id)
        time.sleep(0.8)
    print("  -> if the TOP corners land on the title bar, increase --inset and re-run")
    print("     until top-left/right land just inside the game content.")
    if refused:
        print(f"WARNING: {refused} post(s) REFUSED (grant Accessibility).")
    return 1 if refused else 0


def cmd_click(rest):
    pos, opts = kb._parse_opts(rest, {"inset": (int, 0)})
    if len(pos) != 2:
        print("usage: click <pidA> <pidB> [--inset 0]")
        return 2
    pidA, pidB = int(pos[0]), int(pos[1])
    if pidA == pidB:
        print("pidA and pidB must differ (background isolation needs two processes).")
        return 2
    recs = {r.pid: r for r in kb.enumerate_windows()}
    if pidA not in recs or pidB not in recs:
        print(f"pidA/pidB not both present as TTR windows; found {sorted(recs)}")
        return 1
    inset = opts["inset"]
    a, b = recs[pidA], recs[pidB]
    refused = 0

    print(f"[baseline] bring pid={pidB} FRONT; clicking its CENTER.")
    input("  press Enter when pidB is frontmost... ")
    refused += _click_at(pidB, b.window_id, (0.5, 0.5), inset, b.bundle_id)

    print(f"[central] keep pid={pidA} FRONT; clicking ONLY background pid={pidB} center.")
    input("  press Enter when pidA is frontmost... ")
    print("  -> hold ~0.6s: watch pidB for a DOWN state (press/hover-highlight),")
    print("     then the UP (release). Judge down and up SEPARATELY; pidA unaffected.")
    refused += _click_at(pidB, b.window_id, (0.5, 0.5), inset, b.bundle_id, hold=0.6)

    print(f"[reverse] keep pid={pidB} FRONT; clicking ONLY background pid={pidA} center.")
    input("  press Enter when pidB is frontmost... ")
    print("  -> expect: the click registers in pidA (background), pidB unaffected.")
    refused += _click_at(pidA, a.window_id, (0.5, 0.5), inset, a.bundle_id)

    print(f"[third-app] bring Finder/Terminal FRONT; clicking pid={pidB}.")
    input("  press Enter when a non-game app is frontmost... ")
    print("  -> expect: the click still registers in pidB while neither game is front.")
    refused += _click_at(pidB, b.window_id, (0.5, 0.5), inset, b.bundle_id)

    if refused:
        print(f"WARNING: {refused} post(s) REFUSED (no access / stale target).")
    return 1 if refused else 0


_MOTION_MODES = ("plain", "carrier", "ax")
_MOTION_KINDS = ("hover", "drag")


def _ax_probe(pid):
    """Diagnostic: does AX expose any element tree inside the app's window?

    Returns the first AX window's child count, or -1 if AX is unavailable / has
    no windows. An opaque OpenGL surface typically returns 0 -> AX cannot drive a
    hover pointer; that is the finding we want recorded. Never raises.
    """
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
        )
    except Exception as e:
        print(f"  AX unavailable: {type(e).__name__}: {e}")
        return -1
    try:
        app = AXUIElementCreateApplication(pid)
        err, windows = AXUIElementCopyAttributeValue(app, "AXWindows", None)
        if err != 0 or not windows:
            print(f"  AX: no windows (err={err}).")
            return -1
        err, children = AXUIElementCopyAttributeValue(windows[0], "AXChildren", None)
        n = 0 if (err != 0 or children is None) else len(children)
        print(f"  AX: first window AXChildren count = {n} "
              f"(0 means an opaque OpenGL surface -> AX cannot move hover).")
        return n
    except Exception as e:
        print(f"  AX probe error: {type(e).__name__}: {e}")
        return -1


def cmd_motion(rest):
    pos, opts = kb._parse_opts(rest, {
        "kind": (str, "hover"), "mode": (str, "plain"),
        "inset": (int, 0), "steps": (int, 40),
    })
    if len(pos) != 1:
        print("usage: motion <pid> [--kind hover|drag] [--mode plain|carrier|ax] "
              "[--inset 0] [--steps 40]")
        return 2
    if opts["mode"] not in _MOTION_MODES:
        print(f"invalid --mode {opts['mode']!r}; choose {'|'.join(_MOTION_MODES)}")
        return 2
    if opts["kind"] not in _MOTION_KINDS:
        print(f"invalid --kind {opts['kind']!r}; choose {'|'.join(_MOTION_KINDS)}")
        return 2
    if opts["steps"] < 2:
        print(f"invalid --steps {opts['steps']!r}; need >= 2 (a sweep needs both ends)")
        return 2
    pid = int(pos[0])
    rec = next((r for r in kb.enumerate_windows() if r.pid == pid), None)
    if rec is None:
        print(f"pid={pid} is not a current TTR window.")
        return 1
    Q = kb._quartz()
    kind, mode, inset, steps = opts["kind"], opts["mode"], opts["inset"], opts["steps"]
    bundle, wid = rec.bundle_id, rec.window_id

    if mode == "ax":
        print(f"[motion/ax] probing AX element tree of pid={pid} (diagnostic).")
        _ax_probe(pid)
        print("  -> if AXChildren==0, record AX as NOT viable for hover.")
        return 0

    # plain vs carrier choose the event type for the sweep samples.
    if kind == "hover":
        sweep_type = (Q.kCGEventMouseMoved if mode == "plain"
                      else Q.kCGEventOtherMouseDragged)
        sweep_button = (None if mode == "plain" else Q.kCGMouseButtonCenter)
    else:  # drag
        sweep_type = (Q.kCGEventLeftMouseDragged if mode == "plain"
                      else Q.kCGEventOtherMouseDragged)
        sweep_button = (Q.kCGMouseButtonLeft if mode == "plain"
                        else Q.kCGMouseButtonCenter)

    print(f"[motion] kind={kind} mode={mode}: sweeping pid={pid} content L->R "
          f"in {steps} steps.")
    print("  keep this toon in the BACKGROUND (focus another window first).")
    print("  watch: does the in-game cursor track the sweep? ANY phantom click, "
          "focus change, menu pop, or PHYSICAL cursor movement = side effect (reject).")
    input("  press Enter when this toon is in the background... ")
    # Revalidate ONCE after the (unbounded) prompt: the sweep posts with
    # revalidate=False for speed, so without this a window closed/moved during
    # the wait would be swept blind against a stale/reused PID.
    if not kb.pid_alive_and_ttr(pid, wid, bundle):
        print(f"  REFUSED: pid={pid} window_id={wid} no longer valid after the prompt.")
        return 1

    refused = 0
    # drag/plain needs a real left-down to start a drag, released in finally.
    started_drag = False
    try:
        if kind == "drag" and mode == "plain":
            gx, gy = content_point_to_global((0.05, 0.5), rec.bounds, inset)
            if post_mouse(pid, wid, Q.kCGEventLeftMouseDown, gx, gy,
                          expected_bundle=bundle):
                started_drag = True
            else:
                refused += 1
        for i in range(steps):
            fx = 0.05 + 0.90 * (i / max(1, steps - 1))
            gx, gy = content_point_to_global((fx, 0.5), rec.bounds, inset)
            if not post_mouse(pid, wid, sweep_type, gx, gy, button=sweep_button,
                              revalidate=False):
                refused += 1
            time.sleep(0.03)
    finally:
        if started_drag:
            gx, gy = content_point_to_global((0.95, 0.5), rec.bounds, inset)
            if not post_mouse(pid, wid, Q.kCGEventLeftMouseUp, gx, gy,
                              expected_bundle=bundle):
                refused += 1
    print("  -> record: tracked? (yes/no) and any side effects.")
    if refused:
        print(f"WARNING: {refused} post(s) REFUSED (no access / stale target).")
    return 1 if refused else 0


def cmd_echo(rest):
    _pos, opts = kb._parse_opts(rest, {"seconds": (int, 20), "pid": (int, 0),
                                       "inset": (int, 0)})
    if not kb.preflight_listen_access():
        print("No listen access; grant Input Monitoring to your terminal/python.")
        return 1
    recs = {r.pid: r for r in kb.enumerate_windows()}
    pid = opts["pid"] or (sorted(recs)[0] if recs else 0)
    if pid not in recs:
        print(f"pid={pid} not a current TTR window; found {sorted(recs)}")
        return 1
    Q = kb._quartz()
    import threading
    import Quartz as _Q  # CFRunLoop access

    stats = {"tapped": 0, "ours": 0, "foreign": 0, "tap_disabled": 0}

    mask = ((1 << Q.kCGEventMouseMoved) | (1 << Q.kCGEventLeftMouseDown)
            | (1 << Q.kCGEventLeftMouseUp) | (1 << Q.kCGEventLeftMouseDragged)
            | (1 << Q.kCGEventOtherMouseDragged))

    def _cb(proxy, etype, event, refcon):
        if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
            stats["tap_disabled"] += 1
            Q.CGEventTapEnable(tap, True)
            return event
        stats["tapped"] += 1
        ud = Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData)
        stats[classify_tapped(ud)] += 1
        return event  # listen-only: returning the event is a no-op pass-through

    tap = Q.CGEventTapCreate(
        Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap,
        Q.kCGEventTapOptionListenOnly, mask, _cb, None)
    if not tap:
        print("  ERROR: could not create the listen-only tap (check Input Monitoring).")
        return 1
    src = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
    runloop_holder = {}

    ready = threading.Event()

    def _run():
        rl = _Q.CFRunLoopGetCurrent()
        runloop_holder["rl"] = rl
        _Q.CFRunLoopAddSource(rl, src, _Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(tap, True)
        ready.set()          # tap enabled + source attached -> safe to post
        _Q.CFRunLoopRun()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # Readiness handshake (not a blind sleep): wait until the tap is enabled and
    # attached, then a brief settle for CFRunLoopRun to enter its service cycle.
    # Avoids a false ours==0 from posting before the tap is live.
    if not ready.wait(timeout=2.0):
        print("  ERROR: the tap thread did not become ready within 2s.")
        return 1
    time.sleep(0.1)

    rec = recs[pid]
    gx, gy = content_point_to_global((0.5, 0.5), rec.bounds, opts["inset"])
    print(f"[echo] posting 10 tagged mouse events to pid={pid}; tap is listen-only.")
    posted_ok = 0
    for i in range(10):
        if post_mouse(pid, rec.window_id, Q.kCGEventMouseMoved, gx + i, gy,
                      revalidate=False):
            posted_ok += 1
        time.sleep(0.05)
    if posted_ok == 0:
        print("  WARNING: all 10 posts were REFUSED (grant Accessibility); the echo "
              "result below is INCONCLUSIVE - no tagged events were sent.")
    print(f"[echo] now move/click your REAL mouse for ~{opts['seconds']}s so the tap "
          "sees physical input too.")
    time.sleep(opts["seconds"])

    rl = runloop_holder.get("rl")
    if rl is not None:
        _Q.CFRunLoopStop(rl)
    # Drain the tap thread before reading stats, so no in-flight callback is
    # still writing the dict (mirrors the keyboard spike's listener.join()).
    t.join(timeout=1.0)
    print(f"[echo] {stats}")
    print("  Interpret: ours>0 => our posts RE-ENTER the tap (marker filter is "
          "load-bearing); ours==0 => PID-posted events do not re-enter (marker is "
          "belt-and-suspenders). foreign>0 confirms physical input is seen. "
          "tap_disabled>0 => Phase 1 must handle re-enable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
