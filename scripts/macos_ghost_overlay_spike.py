#!/usr/bin/env python3
"""macOS ghost-cursor overlay feasibility spike (THROWAWAY, operator-run).

Proves whether a Qt frameless / floating / input-transparent overlay owned by
a backgrounded app reliably floats ABOVE the frontmost TTR window, positioned
correctly, on macOS. Pins the exact NSWindow hardening recipe, the
fail-open-vs-closed click-through policy, and empirical coordinate identity.
Results go into the spec's Section 11. NOT production code.

Run on the Mac:
    /usr/bin/python3 scripts/macos_ghost_overlay_spike.py --mode point --x 800 --y 600
    /usr/bin/python3 scripts/macos_ghost_overlay_spike.py --mode follow --anchor center
Add --recipe N to cycle the candidate NSWindow recipes (see RECIPE_CANDIDATES).
"""
from __future__ import annotations

import argparse
import sys

# Fingertip hotspot at 32px, identical to the shipped GhostCursorOverlay.
HOTSPOT = (1, 3)
CURSOR_SIZE = 32


def coordinate_readout(emitted, qt_global, overlay_origin, hotspot=HOTSPOT):
    """Compare the three coordinate samples that decide identity.

    emitted        - the (x, y) Click Sync would emit (screen point).
    qt_global      - the Qt global logical point the overlay was moved to.
    overlay_origin - the overlay window frame top-left actually realized.

    A correct darwin identity run has emitted_vs_qt_delta == (0, 0) and
    origin_error == (0, 0). Negative virtual-desktop coordinates pass through
    untouched."""
    ex, ey = int(emitted[0]), int(emitted[1])
    gx, gy = int(qt_global[0]), int(qt_global[1])
    ox, oy = int(overlay_origin[0]), int(overlay_origin[1])
    expected_origin = (gx - hotspot[0], gy - hotspot[1])
    return {
        "emitted": (ex, ey),
        "qt_global": (gx, gy),
        "overlay_origin": (ox, oy),
        "emitted_vs_qt_delta": (gx - ex, gy - ey),
        "expected_origin": expected_origin,
        "origin_error": (ox - expected_origin[0], oy - expected_origin[1]),
    }
