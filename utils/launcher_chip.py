"""Shared launcher chip labels for the picker dialog and the Settings CC row.

Single source of truth so both surfaces render the same string for a
given launcher slug. Add a new entry here when introducing a new
launcher in services/wine_runtimes.py.
"""

LAUNCHER_CHIP_LABEL = {
    "bottles": "BOTTLES",
    "lutris": "LUTRIS",
    "faugus": "FAUGUS",
    "steam-proton": "STEAM",
    "wine": "WINE",
    "native": "NATIVE",
}
