"""Pure geometry for the emblem radial menu. Qt-free and unit-testable.

Angles are in degrees, screen convention: 0 = right (+x), 90 = down (+y),
-90 = up. The accounts sub-ring reserves the top slot (-90) for the Back
button and distributes the accounts evenly across the remaining slots so the
spacing is dynamic for the number of accounts (never crammed into the bottom).
"""
from __future__ import annotations

import math

MAIN_RING_ANGLES: dict[str, float] = {
    "accounts": -142.0,   # top-left
    "home": -90.0,        # top-center
    "settings": -38.0,    # top-right
    "close": 138.0,       # bottom-left  (dismiss the ring)
    "exit": 42.0,         # bottom-right (quit the app)
}

WINDOWED_RING_ANGLES: dict[str, float] = {
    "accounts": -142.0,    # top-left (matches the transparent ring)
    "transparent": -90.0,  # top-center (the headline action)
    "close": 90.0,         # bottom-center (single dismiss, balanced)
}


def account_ring_angles(n: int) -> list[float]:
    """Angles (deg) for ``n`` account circles, top slot reserved for Back."""
    if n <= 0:
        return []
    step = 360.0 / (n + 1)
    return [-90.0 + step * k for k in range(1, n + 1)]


def polar_point(cx: float, cy: float, radius: float, angle_deg: float) -> tuple[float, float]:
    """Point on the circle of ``radius`` around ``(cx, cy)`` at ``angle_deg``."""
    a = math.radians(angle_deg)
    return (cx + radius * math.cos(a), cy + radius * math.sin(a))
