"""CC head-letter -> species + emoji lookup.

The 3-char head DNA code's first letter encodes species. CC uses its own
letter map (not identical to classic TTR). Verified mappings live in
HEAD_LETTER_TO_SPECIES; unknown letters surface via once-per-letter log.

Verified entries are sourced from user-confirmed observations against
__handleAvatarChooserDone log lines:
  - d -> DOG (Flossbud, Incredible Dog)
  - f -> DUCK (Hector Pepperroni)
  - m -> MOUSE (Soupy)
  - e -> KOALA (Rowdy Koala)
  - t -> RACCOON (Grumpy Biscuit)

CC's binary also names BEAR, CROCODILE, DEER, FISH, FROG, GORILLA, HORSE,
KOALA, MONKEY, MOUSE, ORANGUTAN, OTTER, PANDA, RABBIT, RACCOON, SHEEP,
SWAN, TIGER, TURKEY, WHALE (via `strings`). Their letter mappings are
not verified yet -- letters surface in production via the unknown-letter
log and get added here once a known toon confirms them.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple


logger = logging.getLogger(__name__)

# Verified head-letter -> species name. Add entries here as users confirm.
HEAD_LETTER_TO_SPECIES: dict[str, str] = {
    "d": "DOG",
    "f": "DUCK",
    "m": "MOUSE",
    "e": "KOALA",
    "t": "RACCOON",
}

# Species -> emoji. Covers every species name CC's binary references, so
# once we map a letter the emoji is already wired.
SPECIES_TO_EMOJI: dict[str, str] = {
    "BEAR": "\U0001f43b",
    "CAT": "\U0001f431",
    "CROCODILE": "\U0001f40a",
    "DEER": "\U0001f98c",
    "DOG": "\U0001f436",
    "DUCK": "\U0001f986",
    "FISH": "\U0001f41f",
    "FROG": "\U0001f438",
    "GORILLA": "\U0001f98d",
    "HORSE": "\U0001f434",
    "KOALA": "\U0001f428",
    "MONKEY": "\U0001f435",
    "MOUSE": "\U0001f42d",
    "ORANGUTAN": "\U0001f9a7",
    "OTTER": "\U0001f9a6",
    "PANDA": "\U0001f43c",
    "PIG": "\U0001f437",
    "RABBIT": "\U0001f430",
    "RACCOON": "\U0001f99d",
    "SHEEP": "\U0001f411",
    "SWAN": "\U0001f9a2",
    "TIGER": "\U0001f42f",
    "TURKEY": "\U0001f983",
    "WHALE": "\U0001f40b",
}

_FALLBACK_EMOJI = "❓"

# Letters we've already logged-as-unknown so we don't spam. Reset for tests.
_logged_unknowns: set[str] = set()


def lookup(head_letter: str) -> Tuple[Optional[str], str]:
    """Return (species_name, emoji) for a head-code first letter.

    Unknown letters return (None, "❓") and log once per letter per process.
    """
    species = HEAD_LETTER_TO_SPECIES.get(head_letter)
    if species is None:
        if head_letter not in _logged_unknowns:
            _logged_unknowns.add(head_letter)
            logger.info("[cc_species] unknown head letter: %r", head_letter)
        return (None, _FALLBACK_EMOJI)
    emoji = SPECIES_TO_EMOJI.get(species, _FALLBACK_EMOJI)
    return (species, emoji)
