"""Constants for the silent CC prefs lock.

CC's default keymap accepts BOTH WASD and arrows for movement, which
breaks per-toon keyset assignments (the focused window catches both
keysets natively). TTMT auto-writes CC's preferences.json on startup
to lock movement to a single canonical keyset (WASD), so each window
responds to exactly one keyset and TTMT can route the OTHER keyset
to background windows via the wine bridge.

CANONICAL_KEYMAP values are CC's wire format (the string CC reads
from preferences.json). canonical_to_ttmt_keysyms() returns the
TTMT-internal X11 keysym for each movement action, used by the input
service to compose outbound keystrokes.
"""

from __future__ import annotations

from typing import Literal

Canonical = Literal["wasd", "arrows"]

MOVEMENT_ACTIONS = ("forward", "reverse", "left", "right")

DEFAULT_CANONICAL: Canonical = "wasd"

CANONICAL_KEYMAP: dict[Canonical, dict[str, str]] = {
    "wasd": {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    },
    "arrows": {
        "forward": "arrow_up",
        "reverse": "arrow_down",
        "left": "arrow_left",
        "right": "arrow_right",
    },
}

_CANONICAL_TO_TTMT: dict[Canonical, dict[str, str]] = {
    "wasd": {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    },
    "arrows": {
        "forward": "Up",
        "reverse": "Down",
        "left": "Left",
        "right": "Right",
    },
}


def canonical_to_ttmt_keysyms(canonical: Canonical) -> dict[str, str]:
    return dict(_CANONICAL_TO_TTMT[canonical])
