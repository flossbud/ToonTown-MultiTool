"""Pure parsing of CC Panda3D stdout lines. No I/O, no Qt.

Two record types:
  - AvatarRecord: emitted by `__handleAvatarChooserDone`, once per session
    when the user picks an avatar. Carries name, head DNA code, and the
    5 RGB color tuples (skin, gloves, shirt, shorts, accent).
  - ZoneRecord: emitted by `enterPlayGame` on each hood/zone transition.
    Carries hood_id (playground), zone_id (street), and av_id (avatar this
    refers to; -1 for pre-pick screens).

Both `parse_*` functions return the LAST match in their input text -- CC
logs are append-only so the last record is the freshest state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class AvatarRecord:
    doid: int
    name: str
    head_code: str  # 3-char string like 'dss'
    dna_colors: Tuple[Tuple[float, float, float], ...]  # 5 tuples (skin, gloves, shirt, shorts, accent)


@dataclass
class ZoneRecord:
    hood_id: int
    zone_id: int
    av_id: int


# Avatar chooser line. Layout (per captured logs):
#   __handleAvatarChooserDone: <doid>, '<name>', (<dna_tuple>), <slot_idx>
# Inside dna_tuple, the first 4 entries are strings ('dss', 'ls', 'm', 'f'),
# then 4 RGBA tuples (skin/gloves/shirt/shorts), then 6 ints (clothing),
# then 1 more RGBA tuple (accent), then 2 ints.
_AVATAR_RE = re.compile(
    r"__handleAvatarChooserDone:\s*"
    r"(?P<doid>\d+),\s*"
    r"'(?P<name>[^']+)',\s*"
    r"\(\s*'(?P<head>[a-z]{3})'\s*,\s*"
    r"'[a-z]{2}'\s*,\s*"
    r"'[a-z]'\s*,\s*"
    r"'[a-z]'\s*,\s*"
    r"(?P<rest>.*?)\)\s*,\s*\d+\s*$",
    re.MULTILINE | re.DOTALL,
)

# 4-element RGBA tuples inside the dna_tuple's "rest". We only keep RGB,
# drop the alpha. There are exactly 5 of these in a well-formed record.
_RGBA_RE = re.compile(
    r"\(\s*(-?\d+\.?\d*)\s*,\s*"
    r"(-?\d+\.?\d*)\s*,\s*"
    r"(-?\d+\.?\d*)\s*,\s*"
    r"(-?\d+\.?\d*)\s*\)"
)

_ZONE_RE = re.compile(
    r"enterPlayGame\s+hoodId:(?P<hood>-?\d+)\s+zoneId:(?P<zone>-?\d+)\s+avId:(?P<av>-?\d+)"
)


def parse_avatar_record(text: str) -> Optional[AvatarRecord]:
    """Return the last AvatarRecord in `text`, or None if no match."""
    matches = list(_AVATAR_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    rgba = _RGBA_RE.findall(m.group("rest"))
    if len(rgba) < 5:
        return None
    colors = tuple(
        (float(r), float(g), float(b))
        for (r, g, b, _a) in rgba[:5]
    )
    return AvatarRecord(
        doid=int(m.group("doid")),
        name=m.group("name"),
        head_code=m.group("head"),
        dna_colors=colors,
    )


def parse_latest_zone(text: str, av_id: int) -> Optional[ZoneRecord]:
    """Return the last ZoneRecord matching `av_id`, or None.

    `av_id` filtering is important -- early in a session, CC emits
    enterPlayGame lines with avId:-1 (pre-pick screens). After the user
    picks, lines carry the actual avatar's DOID. We want the latest
    record for our specific avatar, not the most recent line overall.
    """
    target = None
    for m in _ZONE_RE.finditer(text):
        if int(m.group("av")) == av_id:
            target = m
    if target is None:
        return None
    return ZoneRecord(
        hood_id=int(target.group("hood")),
        zone_id=int(target.group("zone")),
        av_id=int(target.group("av")),
    )
