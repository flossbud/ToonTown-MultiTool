"""CC-only dataclass carrying per-toon data extracted from CC stdout.

Kept CC-specific (not unified with TTR) to keep this change small. A
follow-up could unify TTR + CC behind a shared ToonInfo, but the spec
explicitly leaves that open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


# (skin, gloves, shirt, shorts, accent) RGB float tuples in [0, 1].
RGBColors = Tuple[
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
]


@dataclass
class CCToonInfo:
    name: Optional[str] = None
    head_code: Optional[str] = None
    species_letter: Optional[str] = None
    species_name: Optional[str] = None
    species_emoji: Optional[str] = None
    playground: Optional[str] = None
    zone_name: Optional[str] = None
    dna_colors: Optional[RGBColors] = None
