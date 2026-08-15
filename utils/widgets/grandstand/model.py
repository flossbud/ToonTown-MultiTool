"""Display values for the Grandstand launcher, resolved once for both surfaces.

The hero stage and the card shelf must agree about which toon an account shows,
in what pose, and drawn how. They do because they read the same two value
objects built here, from the four stores that own the truth.

Widget-free, not Qt-free: QColor is a value type that needs no QApplication, and
utils.toon_customization_resolve — whose rules this module delegates to — deals
in QColor. This module must never reimplement one of those rules (spec §5); a
second copy of hex validation or pose validation that drifts is exactly the
failure this architecture exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtGui import QColor

from utils.cc_race_assets import asset_stem_for_species
from utils.toon_customization_resolve import resolve_accent, resolve_pose
from utils.widgets.grandstand.palette import game_accent

# Portrait capability is a property of the *game*, not the account: Toontown
# Rewritten publishes a render service and Corporate Clash does not (handoff
# §4.6). 'waiting' is the TTR account that has not discovered a toon yet.
PORTRAIT_RENDER = "render"
PORTRAIT_SPECIES = "species"
PORTRAIT_WAITING = "waiting"

_GAME_PORTRAITS = {"ttr": "rendition", "cc": "species"}

# Poses that draw a whole toon standing on the hero floor; everything else is a
# bust that sits lower and smaller (handoff §8).
FULL_BODY_POSES = frozenset({"waving", "crying", "cake-topper"})

# Shelf cards always draw the same pose so the row reads as one rank, whatever
# each toon's saved pose is (handoff §4.1d).
CARD_POSE = "head"

# The hero has four slots (handoff §4.1b).
LINEUP_SLOTS = 4


def portrait_mode(game: str, has_dna: bool) -> str:
    if _GAME_PORTRAITS.get(game) == "species":
        return PORTRAIT_SPECIES
    return PORTRAIT_RENDER if has_dna else PORTRAIT_WAITING


def footer_text(state: str, has_toon: bool, is_primary: bool) -> str:
    """The card's one-line status (handoff §4.1d). A live session outranks
    identity; without a toon there is no identity to report."""
    if state == "running":
        return "Running"
    if not has_toon:
        return "No toon yet"
    return "Primary" if is_primary else "Last played"


@dataclass(frozen=True)
class RosterEntry:
    """Everything one shelf card draws."""
    account_id: str
    game: str
    label: str
    username: str
    toon_name: Optional[str]
    species: Optional[str]
    dna: str
    accent: str
    footer: str
    portrait_mode: str
    state: str
    message: str
    raw_error: str

    @property
    def display_name(self) -> str:
        return self.toon_name or self.label or self.username or ""

    @property
    def initial(self) -> str:
        name = self.label or self.username or self.toon_name or "?"
        return name[:1].upper()


@dataclass(frozen=True)
class LineupEntry:
    """Everything one hero slot draws."""
    account_id: str
    treatment: str            # standing | bust | cameo | placeholder
    pose: str
    dna: str
    icon_stem: Optional[str]  # race-icon stem in species mode, else None
    species: Optional[str]    # passed straight to paint_race_silhouette
    accent: str
    initial: str


def roster_entry(*, account_id: str, game: str, label: str, username: str,
                 rec, entry: dict, state: str, message: str, raw_error: str,
                 is_primary: bool) -> RosterEntry:
    """Build a card's entry from an account plus its ToonRecord (or None) and
    its resolved customization dict."""
    toon_name = getattr(rec, "toon_name", None) if rec is not None else None
    species = getattr(rec, "species", None) if rec is not None else None
    dna = (getattr(rec, "dna", "") if rec is not None else "") or ""
    rec_accent = getattr(rec, "accent", None) if rec is not None else None

    # Accent resolution is delegated twice rather than validated here: the
    # customization's accent wins, then the account's, then the game's. Calling
    # resolve_accent for both hops means hex validity is defined in exactly one
    # place (`_is_hex` accepts #RGB / #RRGGBB / #RRGGBBAA) and cannot drift.
    account_accent = resolve_accent(
        {"accent": rec_accent},
        QColor(game_accent(game)),
    )
    accent = resolve_accent(
        entry if isinstance(entry, dict) else {}, account_accent
    ).name()

    return RosterEntry(
        account_id=account_id, game=game, label=label, username=username,
        toon_name=toon_name, species=species, dna=dna, accent=accent,
        footer=footer_text(state, toon_name is not None, is_primary),
        portrait_mode=portrait_mode(game, bool(dna)),
        state=state, message=message, raw_error=raw_error,
    )


def lineup_entries(entries: list[RosterEntry], order: list[str],
                   poses: Optional[dict] = None) -> list[LineupEntry]:
    """Resolve the hero lineup for one launch order.

    Two rules from README Q7 live here: the stage holds LINEUP_SLOTS toons, and
    an account with no discovered toon takes a slot **only when one is spare**,
    so checking a toonless account never displaces a real render.
    """
    by_id = {e.account_id: e for e in entries}
    picked = [by_id[aid] for aid in order if aid in by_id]

    real = [e for e in picked if e.toon_name is not None]
    toonless = [e for e in picked if e.toon_name is None]

    chosen = real[:LINEUP_SLOTS]
    spare = LINEUP_SLOTS - len(chosen)
    chosen += toonless[:spare]

    # Restore the caller's order among the accounts that made the cut.
    rank = {aid: i for i, aid in enumerate(order)}
    chosen.sort(key=lambda e: rank.get(e.account_id, 0))

    out: list[LineupEntry] = []
    for e in chosen:
        pose = resolve_pose({"pose": (poses or {}).get(e.account_id)})
        if e.toon_name is None:
            treatment, stem = "placeholder", None
        elif e.portrait_mode == PORTRAIT_SPECIES:
            treatment, stem = "cameo", asset_stem_for_species(e.species)
        elif pose in FULL_BODY_POSES:
            treatment, stem = "standing", None
        else:
            treatment, stem = "bust", None
        out.append(LineupEntry(
            account_id=e.account_id, treatment=treatment, pose=pose, dna=e.dna,
            icon_stem=stem, species=e.species, accent=e.accent,
            initial=e.initial))
    return out
