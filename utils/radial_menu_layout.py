"""Pure geometry for the emblem radial menu. Qt-free and unit-testable.

Angles are in degrees, screen convention: 0 = right (+x), 90 = down (+y),
-90 = up. The accounts sub-ring reserves the top slot (-90) for the Back
button and distributes the accounts evenly across the remaining slots so the
spacing is dynamic for the number of accounts (never crammed into the bottom).
"""
from __future__ import annotations

import math

MAIN_RING_ANGLES: dict[str, float] = {
    "accounts": -142.0,
    "home": -90.0,
    "settings": -38.0,
    "close": 90.0,
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
