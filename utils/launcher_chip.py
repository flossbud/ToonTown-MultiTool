"""Shared launcher chip labels and brand-color tokens.

Single source of truth so both surfaces (picker dialogs and the Settings
CC row) render the same string and the same color for a given launcher
slug. Add a new entry to BOTH dicts when introducing a new launcher in
services/wine_runtimes.py.
"""

LAUNCHER_CHIP_LABEL = {
    "bottles": "BOTTLES",
    "lutris": "LUTRIS",
    "faugus": "FAUGUS",
    "steam-proton": "STEAM",
    "wine": "WINE",
    "native": "NATIVE",
}

# Per-slug gradient stops: (start_hex, end_hex). Rendered as a 135deg-ish
# diagonal (qlineargradient from top-left to bottom-right) by chip_style_for.
# AUTO and PROTON are not real launchers; they are used by the compat picker
# only (AUTO == "Use Steam's selection" card, PROTON == specific Proton tool).
LAUNCHER_CHIP_COLOR = {
    "wine":          ("#d04545", "#7a2222"),
    "faugus":        ("#e08640", "#a85522"),
    "bottles":       ("#9b6be0", "#5a3eb2"),
    "lutris":        ("#4a8fe7", "#1e63d6"),
    "steam-proton":  ("#2a475e", "#1b2838"),
    "native":        ("#4cb960", "#2d7a40"),
    "auto":          ("#0077ff", "#3399ff"),
    "proton":        ("#5a6680", "#3a4660"),
}

_FALLBACK_PAIR = ("#6a7280", "#4b5563")


def chip_style_for(slug: str) -> str:
    """Return a QSS background-gradient string for the chip of `slug`.

    Used by PickerCard's chip QLabel. Falls back to a neutral gray pair so
    a new launcher slug never crashes the picker. Uses the `background:`
    shorthand because Qt QSS's `background-image:` property only accepts
    URL-based images, not gradients.
    """
    start, end = LAUNCHER_CHIP_COLOR.get(slug, _FALLBACK_PAIR)
    return (
        f"background: qlineargradient("
        f"x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {start}, stop:1 {end});"
    )
