"""Pure constants for the Per-toon control isolation feature.

Two parallel maps because we cross a translation boundary:

- CANONICAL_KEYMAP holds the value strings CC writes into its preferences.json
  keymap dict ('arrow_up', 'w', etc.). These are CC's wire format.
- canonical_to_ttmt_keysyms() returns TTMT-internal keysyms ('Up', 'w', etc.)
  that input_service uses to compose outbound keystrokes. These are X11
  keysyms.

cc_settings._CC_VALUE_TO_KEYSYM already handles wire->TTMT conversion for
reads; this module supplies the matching values for writes and the reverse
mapping for the routing layer.
"""

from __future__ import annotations

from typing import Literal

Canonical = Literal["wasd", "arrows"]

MOVEMENT_ACTIONS = ("forward", "reverse", "left", "right")

DEFAULT_CANONICAL: Canonical = "wasd"

# Values written into CC's preferences.json `keymap` dict.
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

# TTMT-internal keysyms for each canonical, used by the input service to
# look up outbound keys when forwarding to background CC toons.
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
    """Return the action->TTMT-keysym mapping for the given canonical."""
    return dict(_CANONICAL_TO_TTMT[canonical])
