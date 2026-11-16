"""The Appearance editor's edit draft (handoff §6.2, appearance half).

Widget-free. The editor's controls write into one of these, the view hands a
copy to LaunchTab on Save, and LaunchTab performs the write. Cancel drops it:
nothing here persists and nothing here reads a store.

The stored look is the dict `ToonCustomizationOverlay` writes and the
`utils.toon_customization_resolve` helpers read. This draft edits five
*groups* of it (accent, pose, backdrop, pattern, framing) and leaves the rest
alone: `apply_to()` rewrites a group only when its effective value changed
since open, so body colour, silhouette effects, a Corporate Clash icon choice
and anything else this editor does not expose survive a Save untouched, and
an untouched editor saves the entry it was given.

Seeding goes through the resolve helpers and never re-implements them: hex
validity, gradient-beats-colour, pose validation and transform clamping are
each defined in exactly one place.
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass
from typing import Optional

from PySide6.QtGui import QColor

from utils.rendition_poses import POSE_NAMES
from utils.toon_customization_resolve import (
    resolve_accent, resolve_portrait_brush, resolve_portrait_pattern,
    resolve_portrait_transform, resolve_pose,
)
from utils.toon_pattern_assets import PATTERN_NAMES
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.model import (
    PORTRAIT_RENDER, PORTRAIT_SPECIES, PORTRAIT_WAITING, portrait_mode,
)

FILL_SOLID = "solid"
FILL_GRADIENT = "gradient"
DEFAULT_POSE = "portrait"

# Handoff §8: human names only, never the API string.
POSE_LABELS = {
    "portrait": "Portrait",
    "portrait-delighted": "Delighted",
    "portrait-grin": "Grin",
    "portrait-thinking": "Thinking",
    "portrait-surprise": "Surprised",
    "portrait-sleep": "Sleepy",
    "portrait-fall": "Falling",
    "portrait-birthday": "Birthday",
    "head": "Head",
    "waving": "Waving",
    "crying": "Crying",
    "cake-topper": "Cake topper",
    "laffmeter": "Laff meter",
}

# The pattern chips (handoff §4.2). The store knows five more; one of those
# is offered only while it is the stored pattern (see pattern_choices).
PATTERN_CHOICES = (("dots", "Dots"), ("chevrons", "Chevrons"), ("stars", "Stars"))

# Surprise me rolls a pose from the first eight: the busts (handoff §5).
SURPRISE_POSES = 8

G_ACCENT = "accent"
G_POSE = "pose"
G_BACKDROP = "backdrop"
G_PATTERN = "pattern"
G_FRAMING = "framing"
GROUPS = (G_ACCENT, G_POSE, G_BACKDROP, G_PATTERN, G_FRAMING)

ZOOM_RANGE = (0.5, 3.0)
OFFSET_RANGE = (-1.0, 1.0)
ROTATE_RANGE = (-180.0, 180.0)


def _hex(color: QColor) -> str:
    """A QColor as the hex string the store holds; alpha kept when present."""
    if color.alpha() < 255:
        return color.name(QColor.HexArgb)
    return color.name()


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], float(value)))


def pattern_label(name: str) -> str:
    for key, label in PATTERN_CHOICES:
        if key == name:
            return label
    return name.replace("_", " ").capitalize()


def look_entry(index: int) -> dict:
    """One curated Look as a stored entry, for painting its swatch."""
    _name, fill, start, end, pattern, pattern_color, accent = gp.LOOKS[index]
    portrait: dict = {}
    if fill == FILL_GRADIENT:
        portrait["gradient"] = {"start": start, "end": end}
    else:
        portrait["color"] = start
    if pattern:
        portrait["pattern"] = {"name": pattern, "color": pattern_color}
    entry: dict = {"portrait": portrait}
    if accent:
        entry["accent"] = accent
    return entry


@dataclass
class AppearanceDraft:
    """One toon's look while it is being edited.

    `base` is the stored entry at open time. `accent_fallback` is what the
    ring shows while `accent` is unset: the toon's own accent, else the
    game's. `toon_name` is None for an account with no discovered toon, in
    which case there is no look to edit and nothing to save."""
    account_id: str
    account_name: str
    game: str
    toon_name: Optional[str]
    species: Optional[str]
    dna: str
    accent_fallback: str
    base: dict
    accent: Optional[str] = None
    pose: str = DEFAULT_POSE
    fill: str = FILL_SOLID
    color: Optional[str] = None          # None = automatic backdrop
    g_start: str = gp.DEFAULT_GRADIENT[0]
    g_end: str = gp.DEFAULT_GRADIENT[1]
    pat_name: Optional[str] = None
    pat_color: str = gp.DEFAULT_PATTERN_COLOR
    zoom: float = 1.0
    off_x: float = 0.0
    off_y: float = 0.0
    rotate: float = 0.0
    opened: Optional[dict] = None        # group -> effective value at open

    def __post_init__(self) -> None:
        if self.opened is None:
            self.opened = self._group_values()

    # ── construction ───────────────────────────────────────────────────────

    @classmethod
    def from_entry(cls, *, account_id: str, account_name: str, game: str,
                   toon_name: Optional[str], species: Optional[str], dna: str,
                   accent_fallback: str, entry) -> "AppearanceDraft":
        base = copy.deepcopy(entry) if isinstance(entry, dict) else {}
        unset = QColor()                 # invalid: "the resolver fell back"

        accent = resolve_accent(base, unset)
        brush = resolve_portrait_brush(base, unset)
        portrait = base.get("portrait")
        portrait = portrait if isinstance(portrait, dict) else {}
        # The solid colour on its own, so a look stored as a gradient still
        # shows its colour (the old overlay keeps both) if the user turns the
        # gradient off.
        solid = resolve_portrait_brush(
            {"portrait": {"color": portrait.get("color")}}, unset).color()
        fill = FILL_SOLID
        g_start, g_end = gp.DEFAULT_GRADIENT
        gradient = brush.gradient()
        if gradient is not None:
            stops = gradient.stops()
            fill = FILL_GRADIENT
            g_start, g_end = _hex(stops[0][1]), _hex(stops[-1][1])

        pattern = resolve_portrait_pattern(base)
        try:
            zoom, off_x, off_y, rotate = resolve_portrait_transform(base)
        except (TypeError, ValueError):
            # A hand-edited file with a non-numeric value: read as neutral.
            zoom, off_x, off_y, rotate = 1.0, 0.0, 0.0, 0.0

        return cls(
            account_id=account_id, account_name=account_name, game=game,
            toon_name=toon_name or None, species=species, dna=dna or "",
            accent_fallback=accent_fallback, base=base,
            accent=_hex(accent) if accent.isValid() else None,
            pose=resolve_pose(base, DEFAULT_POSE),
            fill=fill,
            color=_hex(solid) if solid.isValid() else None,
            g_start=g_start, g_end=g_end,
            pat_name=pattern[0] if pattern is not None else None,
            pat_color=(_hex(pattern[1]) if pattern is not None
                       else gp.DEFAULT_PATTERN_COLOR),
            zoom=zoom, off_x=off_x, off_y=off_y, rotate=rotate)

    def copy(self) -> "AppearanceDraft":
        """A snapshot: what leaves the view never changes under a consumer."""
        return dataclasses.replace(
            self, base=copy.deepcopy(self.base), opened=dict(self.opened))

    # ── identity and capability (handoff §4.6) ──────────────────────────────

    @property
    def has_toon(self) -> bool:
        return bool(self.toon_name)

    @property
    def mode(self) -> str:
        """render | species | waiting. A toon with no DNA cannot be drawn by
        the render service, so it waits like an account with no toon."""
        mode = portrait_mode(self.game, bool(self.dna))
        if mode == PORTRAIT_SPECIES:
            return mode
        return PORTRAIT_RENDER if (self.has_toon and self.dna) else PORTRAIT_WAITING

    @property
    def can_pose(self) -> bool:
        return self.mode == PORTRAIT_RENDER

    @property
    def can_frame(self) -> bool:
        """Zoom, turn and drag need a render to move. Corporate Clash's badge
        painter ignores the stored transform, so offering it there would
        write values nothing draws."""
        return self.mode == PORTRAIT_RENDER

    @property
    def store_key(self) -> str:
        return f"{self.game}::{self.toon_name}" if self.has_toon else ""

    def resolved_accent(self) -> str:
        return self.accent or self.accent_fallback

    # ── groups ─────────────────────────────────────────────────────────────

    def _group_values(self) -> dict:
        if self.fill == FILL_GRADIENT:
            backdrop = (FILL_GRADIENT, self.g_start, self.g_end)
        else:
            backdrop = (FILL_SOLID, self.color)
        pattern = (self.pat_name, self.pat_color) if self.pat_name else None
        framing = (round(self.zoom, 4), round(self.off_x, 4),
                   round(self.off_y, 4), round(self.rotate, 2))
        return {G_ACCENT: self.accent, G_POSE: self.pose,
                G_BACKDROP: backdrop, G_PATTERN: pattern, G_FRAMING: framing}

    def changed_groups(self) -> set:
        now = self._group_values()
        return {g for g in GROUPS if now[g] != self.opened.get(g)}

    def is_dirty(self) -> bool:
        """Drives the toon switcher's discard warning (handoff §6.2)."""
        return bool(self.changed_groups())

    # ── edits ──────────────────────────────────────────────────────────────

    def set_framing(self, *, zoom=None, off_x=None, off_y=None, rotate=None) -> None:
        """Clamped to resolve_portrait_transform's ranges, so what the canvas
        shows is what the resolver would hand production after a Save."""
        if zoom is not None:
            self.zoom = round(_clamp(zoom, ZOOM_RANGE), 2)
        if off_x is not None:
            self.off_x = round(_clamp(off_x, OFFSET_RANGE), 4)
        if off_y is not None:
            self.off_y = round(_clamp(off_y, OFFSET_RANGE), 4)
        if rotate is not None:
            self.rotate = float(round(_clamp(rotate, ROTATE_RANGE)))

    def swap_gradient(self) -> None:
        self.g_start, self.g_end = self.g_end, self.g_start

    def pattern_choices(self) -> list[tuple[str, str]]:
        """The chips after `None`: the handoff's three, plus the pattern this
        look was opened with when it is one of the store's other five, so a
        look made in the old customizer can be seen and reselected."""
        choices = list(PATTERN_CHOICES)
        opened = self.opened.get(G_PATTERN)
        name = opened[0] if opened else None
        if (name in PATTERN_NAMES
                and name not in {key for key, _label in PATTERN_CHOICES}):
            choices.append((name, pattern_label(name)))
        return choices

    def apply_look(self, index: int) -> None:
        """One click sets fill, stops, pattern, pattern colour and accent
        together (handoff §4.2)."""
        _name, fill, start, end, pattern, pattern_color, accent = gp.LOOKS[index]
        self.fill = fill
        self.g_start, self.g_end = start, end
        self.color = start
        self.pat_name = pattern
        self.pat_color = pattern_color
        self.accent = accent

    def matching_look(self) -> Optional[int]:
        """The Look these values amount to, however they were reached, so a
        hand edit that lands on a Look lights it (the reference build's
        `looksLike`)."""
        for index, look in enumerate(gp.LOOKS):
            _name, fill, start, end, pattern, _pattern_color, accent = look
            if fill != self.fill or pattern != self.pat_name or accent != self.accent:
                continue
            if fill == FILL_GRADIENT:
                if (self.g_start, self.g_end) == (start, end):
                    return index
            elif self.color == start:
                return index
        return None

    def reset(self) -> None:
        """Reset all: everything this editor exposes goes back to unset. The
        backdrop becomes automatic rather than a colour of the editor's own
        choosing, as the old customizer's reset does."""
        self.accent = None
        self.pose = DEFAULT_POSE
        self.fill = FILL_SOLID
        self.color = None
        self.pat_name = None
        self.zoom, self.off_x, self.off_y, self.rotate = 1.0, 0.0, 0.0, 0.0

    def surprise(self, rng) -> None:
        """A random Look, plus a pose and a framing where those exist
        (handoff §5). `rng` is a random.Random so a test can seed it."""
        self.apply_look(rng.randrange(len(gp.LOOKS)))
        if self.can_pose:
            self.pose = POSE_NAMES[rng.randrange(SURPRISE_POSES)]
        if self.can_frame:
            self.set_framing(zoom=1.0 + rng.random() * 0.6,
                             off_x=rng.random() * 0.3 - 0.15,
                             off_y=rng.random() * 0.3 - 0.15)

    # ── output ─────────────────────────────────────────────────────────────

    def apply_to(self, entry) -> dict:
        """`entry` with this draft's changed groups written in the stored
        schema's canonical form; every other key exactly as it was. Returns
        a new dict."""
        out = copy.deepcopy(entry) if isinstance(entry, dict) else {}
        changed = self.changed_groups()
        if not changed:
            return out

        if G_ACCENT in changed:
            if self.accent:
                out["accent"] = self.accent
            else:
                out.pop("accent", None)
        if G_POSE in changed:
            if self.pose == DEFAULT_POSE:
                out.pop("pose", None)
            else:
                out["pose"] = self.pose

        if not changed & {G_BACKDROP, G_PATTERN, G_FRAMING}:
            return out
        portrait = out.get("portrait")
        portrait = portrait if isinstance(portrait, dict) else {}
        if G_BACKDROP in changed:
            # Gradient or colour, never both: gradient wins on read, so a
            # colour left beside it would be dead weight (handoff §7).
            if self.fill == FILL_GRADIENT:
                portrait["gradient"] = {"start": self.g_start, "end": self.g_end}
                portrait.pop("color", None)
            else:
                portrait.pop("gradient", None)
                if self.color:
                    portrait["color"] = self.color
                else:
                    portrait.pop("color", None)
        if G_PATTERN in changed:
            if self.pat_name:
                portrait["pattern"] = {"name": self.pat_name,
                                       "color": self.pat_color}
            else:
                portrait.pop("pattern", None)
        if G_FRAMING in changed:
            identity = (abs(self.zoom - 1.0) < 1e-6 and abs(self.off_x) < 1e-6
                        and abs(self.off_y) < 1e-6 and abs(self.rotate) < 1e-6)
            if identity:
                portrait.pop("transform", None)
            else:
                portrait["transform"] = {
                    "zoom": self.zoom, "offset_x": self.off_x,
                    "offset_y": self.off_y, "rotate": self.rotate}
        if portrait:
            out["portrait"] = portrait
        else:
            out.pop("portrait", None)
        return out

    def preview_entry(self) -> dict:
        """What a Save would store if nothing else touched the entry: the
        dict every painter in the editor reads, through the resolve rules."""
        return self.apply_to(self.base)
