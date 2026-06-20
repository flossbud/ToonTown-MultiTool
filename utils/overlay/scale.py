"""Uniform-scale math for transparent-mode resize. Pure, UI-free, importable on any platform."""
from __future__ import annotations

SCALE_MIN = 0.5
SCALE_MAX = 1.75
SCALE_STEP = 0.08      # per wheel notch
SNAP_TARGET = 1.0
SNAP_WINDOW = 0.04     # snap to 1.0 when this close

def clamp_scale(value: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, value))

def step_scale(current: float, notches: int) -> float:
    """Apply `notches` wheel steps to `current`, clamp to range, snap to 100% near it."""
    value = clamp_scale(current + notches * SCALE_STEP)
    if abs(value - SNAP_TARGET) < SNAP_WINDOW + 1e-9:
        value = SNAP_TARGET
    return value
