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

import dataclasses
import os
import sys
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
    phases = [("move", 0), ("down", 1), ("up", 1)]
    plan = []
    for kind, cc in phases:
        for tid in target_ids:
            plan.append((kind, tid, EventSpec(kind, point, cc)))
    return plan


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
