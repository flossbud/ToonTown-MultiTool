"""Line protocol between the app and the ghost-renderer helper process.

Why a helper process exists (ledger CP17): with the ghost pipeline fully
frame-paced and the window-server probe off the frame path, gloves still
rendered at ~50-60Hz - a bare 4ms reference timer gapped 17-22ms under live
load, 1:1 with the frame driver, so the app's single Qt loop + GIL is the
in-process cadence floor. The renderer is a separate process whose loop does
nothing but draw gloves; positions reach it from the CAPTURE THREAD over its
stdin pipe, bypassing the app's GUI loop entirely.

Wire format: newline-delimited ASCII, whitespace-separated fields. Pure
codec - no I/O, no Qt - so both sides and the tests share one source of
truth. Unknown/garbage lines decode to None and are skipped by the reader
(forward compatibility: an older renderer ignores what it does not know).

Messages:
  P <slot> <x> <y> <wid>   glove position (logical/global px; wid "-" =
                           unknown -> occlusion fails open for that glove)
  F <wid>                  focused game window ("-" = none): the renderer
                           suppresses any glove whose CURRENT wid matches
                           (the focused window never shows a ghost)
  C                        clear: hide every glove now
  Q                        quit the renderer
"""
from __future__ import annotations

from typing import Optional


def encode_position(slot: int, x: int, y: int, wid) -> str:
    return f"P {int(slot)} {int(x)} {int(y)} {wid if wid else '-'}\n"


def encode_focus(wid) -> str:
    return f"F {wid if wid else '-'}\n"


def encode_clear() -> str:
    return "C\n"


def encode_quit() -> str:
    return "Q\n"


def decode_line(line: str) -> Optional[tuple]:
    """One wire line -> a message tuple, or None for blank/unknown/garbage.

    ("position", slot, x, y, wid|None) | ("focus", wid|None) | ("clear",)
    | ("quit",)
    """
    parts = line.split()
    if not parts:
        return None
    kind = parts[0]
    try:
        if kind == "P" and len(parts) == 5:
            wid = None if parts[4] == "-" else parts[4]
            return ("position", int(parts[1]), int(parts[2]),
                    int(parts[3]), wid)
        if kind == "F" and len(parts) == 2:
            return ("focus", None if parts[1] == "-" else parts[1])
        if kind == "C":
            return ("clear",)
        if kind == "Q":
            return ("quit",)
    except (ValueError, IndexError):
        return None
    return None
