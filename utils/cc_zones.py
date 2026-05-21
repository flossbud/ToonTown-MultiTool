"""CC zone_id -> (playground, zone_name) lookup.

CC emits `enterPlayGame hoodId:X zoneId:Y avId:Z` on every zone transition.
hoodId identifies the playground (round-thousands like 2000, 4000); zoneId
identifies the specific street within (e.g., 2100, 2200).

Only verified entries are committed here. Unknowns surface via the
once-per-id log so we can grow the table empirically during dogfooding.

Verified from CC stdout captures:
  - hood 2000 = Toontown Central (hood-only confirmation; specific
    streets not yet observed against ground truth)
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple


logger = logging.getLogger(__name__)


HOOD_ID_TO_PLAYGROUND: dict[int, str] = {
    2000: "Toontown Central",
}

# Specific zone_id -> street name. Populated as we observe ground-truth
# zone IDs (user confirms "I'm on Loopy Lane" matches zone_id N).
ZONE_ID_TO_NAME: dict[int, str] = {
    # No verified street names yet.
}

_logged_unknown_hoods: set[int] = set()
_logged_unknown_zones: set[int] = set()


def lookup(zone_id: int, hood_id: int) -> Tuple[Optional[str], Optional[str]]:
    """Return (playground_name, zone_name) for a zone+hood pair.

    Rules:
      - hood known + zone matches hood -> (playground, None) (user is at the
        playground itself, no specific street)
      - hood known + specific zone -> (playground, zone_name)
      - hood known + unknown zone -> (playground, None) + log zone once
      - hood unknown -> (None, None) + log hood once
    """
    playground = HOOD_ID_TO_PLAYGROUND.get(hood_id)
    if playground is None:
        if hood_id not in _logged_unknown_hoods:
            _logged_unknown_hoods.add(hood_id)
            logger.info("[cc_zones] unknown hood id: %d", hood_id)
        return (None, None)

    # zone_id == hood_id is the "at the playground, no specific street" case.
    if zone_id == hood_id:
        return (playground, None)

    zone_name = ZONE_ID_TO_NAME.get(zone_id)
    if zone_name is None and zone_id not in _logged_unknown_zones:
        _logged_unknown_zones.add(zone_id)
        logger.info(
            "[cc_zones] unknown zone id: %d (hood %d / %s)",
            zone_id, hood_id, playground,
        )
    return (playground, zone_name)
