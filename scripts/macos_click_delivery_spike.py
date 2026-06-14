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
