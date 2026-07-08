"""Per-game display metadata + set-accent cycle. Game-agnostic: adding a third
game later is a GAME_META entry + a banner asset (no other code change)."""
from __future__ import annotations
from dataclasses import dataclass

from utils.theme_manager import V2_ACCENTS


@dataclass(frozen=True)
class GameMeta:
    key: str
    title: str
    short: str
    accent_c: str
    accent_b: str
    banner_asset: str


# Ships TTR + CC only. Accents are the picker's game-identity colors.
GAME_META = {
    "ttr": GameMeta("ttr", "Toontown Rewritten", "TTR", "#4A8FE7", "#6ba8f0", "ttr-banner.png"),
    "cc":  GameMeta("cc",  "Corporate Clash",    "CC",  "#F26D21", "#ff8f4d", "cc-banner.png"),
    # "ti": GameMeta("ti", "Toontown Infinite", "TI", "#8B4FD6", "#a97ce6", "ti-banner.png"),
}

# The set-card identity ramp: an ordered subset of V2_ACCENTS (jewel tones that
# stay saturated when darkened). NOT get_set_color() (the old muddy palette).
_SET_ACCENT_CYCLE = ("blue", "red", "yellow", "green", "orange", "pink", "teal")


def set_accent(index: int) -> tuple[str, str]:
    """(c, b) accent for the set at `index`, cycling the V2_ACCENTS subset."""
    a = V2_ACCENTS[_SET_ACCENT_CYCLE[index % len(_SET_ACCENT_CYCLE)]]
    return a["c"], a["b"]
