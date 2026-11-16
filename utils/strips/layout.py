"""Where each block of a strip sits. Pure geometry in logical px at scale 1.0,
origin at the top-left of the row (glow margins are the widget's business)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QRectF

from utils.strips.model import StripModel
from utils.strips.tokens import StripStyle, snap, snap_up

HOME = "home"
PORTRAIT = "portrait"
NAME = "name"
KEEP_ALIVE = "keep_alive"
CLICK_SYNC = "click_sync"
SEPARATOR = "sep"
KEYSET = "keyset"
ADD = "add"
ENABLE = "enable"

# Kinds that take the pointer. Separators are decoration.
INTERACTIVE = (HOME, PORTRAIT, NAME, KEEP_ALIVE, CLICK_SYNC, KEYSET, ADD, ENABLE)

# Narrow-window collapse, in the order it is applied.
FULL = 0
NO_NAME = 1          # portrait only; the name moves into the counters
ACTIVE_SET_ONLY = 2  # and only the active keyset number plus the +

# A strip must leave this much of the client width free (12 px each side).
CLIENT_MARGIN = 24.0


@dataclass(frozen=True)
class Block:
    kind: str
    rect: QRectF
    number: int = 0          # keyset number for KEYSET blocks

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.number)


@dataclass(frozen=True)
class StripLayout:
    blocks: tuple[Block, ...]
    width: float
    height: float
    collapse: int

    def find(self, kind: str, number: int = 0) -> Block | None:
        for b in self.blocks:
            if b.kind == kind and b.number == number:
                return b
        return None

    def identity_rect(self) -> QRectF:
        """Portrait plus name plate: the hover and right-click target, and
        what the counters centre under."""
        rect = QRectF()
        for b in self.blocks:
            if b.kind in (PORTRAIT, NAME):
                rect = rect.united(b.rect) if rect.isValid() else QRectF(b.rect)
        return rect

    def hit(self, x: float, y: float) -> Block | None:
        """The interactive block under a row-local point, top-most first
        (the portrait overlaps the name plate's tucked end)."""
        found = None
        for b in self.blocks:
            if b.kind in INTERACTIVE and b.rect.contains(x, y):
                if b.kind == PORTRAIT:
                    return b
                found = found or b
        return found


def name_plate_width(style: StripStyle, text_width: float) -> float:
    natural = (style.name_border * 2 + style.name_pad_left
               + text_width + style.name_pad_right)
    return max(style.name_min_w, natural)


def visible_keysets(model: StripModel, collapse: int) -> tuple[int, ...]:
    if collapse >= ACTIVE_SET_ONLY:
        if model.active in model.keysets:
            return (model.active,)
        return model.keysets[:1]
    return model.keysets


def layout_strip(model: StripModel, style: StripStyle,
                 measure_name: Callable[[str], float],
                 collapse: int = FULL, device_scale: float = 0.0) -> StripLayout:
    """Lay the row out left to right, everything vertically centred.

    With a `device_scale` (design px to device px) and a style snapped to it
    (tokens.snapped_style), every edge lands on a whole device pixel: the
    two things the style cannot settle, a block's centred top and the name
    plate's text-driven width, are snapped here."""
    h = style.height
    blocks: list[Block] = []
    x = 0.0

    def top(height: float) -> float:
        y = (h - height) / 2.0
        return snap(y, device_scale) if device_scale > 0 and y > 0 else y

    def centred(width: float, height: float) -> QRectF:
        return QRectF(x, top(height), width, height)

    def advance(width: float, extra: float = 0.0) -> None:
        nonlocal x
        x += width + extra + style.gap

    if model.home:
        blocks.append(Block(HOME, centred(style.home, style.home)))
        advance(style.home, style.home_margin)

    # Identity: the plate is tucked under the portrait, no gap inside.
    blocks.append(Block(PORTRAIT, centred(style.portrait, style.portrait)))
    identity_w = style.portrait
    if collapse < NO_NAME:
        plate_w = name_plate_width(style, measure_name(model.name))
        if device_scale > 0:
            plate_w = snap_up(plate_w, device_scale)
        plate_x = x + style.portrait - style.name_tuck
        blocks.append(Block(NAME, QRectF(plate_x, top(style.name_h),
                                         plate_w, style.name_h)))
        identity_w = style.portrait - style.name_tuck + plate_w
    advance(identity_w)

    tools = [k for k, on in ((KEEP_ALIVE, model.keep_alive),
                             (CLICK_SYNC, model.click_sync)) if on is not None]
    for kind in tools:
        blocks.append(Block(kind, centred(style.block, style.block)))
        advance(style.block)

    def separator() -> None:
        nonlocal x
        x += style.sep_margin
        blocks.append(Block(SEPARATOR, centred(style.sep_w, style.sep_h)))
        advance(style.sep_w, style.sep_margin)

    if tools:
        separator()

    for number in visible_keysets(model, collapse):
        blocks.append(Block(KEYSET, centred(style.block, style.block), number))
        advance(style.block)
    if model.show_add:
        blocks.append(Block(ADD, centred(style.block, style.block)))
        advance(style.block)

    separator()
    blocks.append(Block(ENABLE, centred(style.block, style.block)))
    x += style.block

    return StripLayout(tuple(blocks), x, h, collapse)


def fit_strip(model: StripModel, style: StripStyle,
              measure_name: Callable[[str], float],
              client_width: float | None,
              device_scale: float = 0.0) -> StripLayout:
    """The widest layout that fits the game window's client width. With no
    width to fit (None) the strip is laid out in full."""
    result = layout_strip(model, style, measure_name, FULL, device_scale)
    if client_width is None:
        return result
    limit = client_width - CLIENT_MARGIN
    for collapse in (NO_NAME, ACTIVE_SET_ONLY):
        if result.width <= limit:
            break
        result = layout_strip(model, style, measure_name, collapse, device_scale)
    return result
