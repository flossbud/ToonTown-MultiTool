"""Parse a packed TTR ToonDNA hex string into (species_name, accent_hex).

TTR "style"/DNA is the classic ToonDNA byte structure: byte 0 is 0x74 ('t' for
toon), byte 1 is the head index into ``toonHeadTypes``. The first letter of the
head-type code identifies the animal (species). Qt-free and unit-testable.

Species decoding was confirmed empirically against 5 real live-config toons and
their cached Rendition portraits (byte1: 0->DOG, 5->CAT, 9->HORSE, 13->MOUSE,
16->RABBIT), matching the canonical ``toonHeadTypes`` ordering below.

Accent (head color) is encoded at byte 14, but the index->hex mapping is TTR's
extended toon-color palette, which is not available in this repo and is not
guessed here. The authoritative accent is the live ``headColor`` hex from the
local API; ``parse_dna`` returns ``accent=None`` and callers fall back to the
game accent. The ``(species, accent)`` return shape is kept forward-compatible
for the day a validated palette lands.
"""
from __future__ import annotations

# Canonical ToonDNA head-type codes, indexed by the DNA head byte. The first
# letter is the animal. Ordering (dog, cat, horse, mouse[2 heads], rabbit,
# duck, monkey, bear, pig) is the standard ToonDNA table, empirically consistent
# with the confirmed samples above.
_TOON_HEAD_TYPES: tuple[str, ...] = (
    "dls", "dss", "dsl", "dll",   # 0-3   dog
    "cls", "css", "csl", "cll",   # 4-7   cat
    "hls", "hss", "hsl", "hll",   # 8-11  horse
    "mls", "mss",                 # 12-13 mouse
    "rls", "rss", "rsl", "rll",   # 14-17 rabbit
    "fls", "fss", "fsl", "fll",   # 18-21 duck
    "pls", "pss", "psl", "pll",   # 22-25 monkey
    "bls", "bss", "bsl", "bll",   # 26-29 bear
    "sls", "sss", "ssl", "sll",   # 30-33 pig
)

# Head-type first letter -> uppercase species name, aligned with utils/cc_species
# naming so both games share cc_race_assets.asset_stem_for_species (all nine map
# to an assets/ccraces/<stem>.png).
_LETTER_TO_SPECIES: dict[str, str] = {
    "d": "DOG",
    "c": "CAT",
    "h": "HORSE",
    "m": "MOUSE",
    "r": "RABBIT",
    "f": "DUCK",
    "p": "MONKEY",
    "b": "BEAR",
    "s": "PIG",
}


def parse_dna(dna: str) -> tuple[str | None, str | None]:
    """Return (species_name, accent_hex) for a packed ToonDNA hex string.

    species_name is an uppercase animal name (see _LETTER_TO_SPECIES) or None.
    accent_hex is currently always None (no validated TTR color palette in-repo;
    live headColor is the accent source of truth). Non-toon / short / non-hex
    input returns (None, None).
    """
    if not isinstance(dna, str) or not dna:
        return (None, None)
    try:
        b = bytes.fromhex(dna)
    except ValueError:
        return (None, None)
    if len(b) < 2 or b[0] != 0x74:
        return (None, None)
    head = b[1]
    if head >= len(_TOON_HEAD_TYPES):
        return (None, None)
    species = _LETTER_TO_SPECIES.get(_TOON_HEAD_TYPES[head][0])
    return (species, None)
