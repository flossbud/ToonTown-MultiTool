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


def cmd_probe_rect(rest):
    raise NotImplementedError


def cmd_click(rest):
    raise NotImplementedError


def cmd_motion(rest):
    raise NotImplementedError


def cmd_echo(rest):
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
