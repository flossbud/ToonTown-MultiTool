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
