"""CC race PNG asset lookup and caching.

The PNGs live in `assets/ccraces/` (one per race). The first letter of the
toon's head DNA code maps to a species name (see `utils/cc_species.py`);
this module maps species names to asset filename stems.

Most species map by simple lowercase (DOG -> dog.png). Where CC's binary
uses a different name than the asset, add an entry to SPECIES_ALIAS.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtGui import QPixmap


# Aliases: CC species names that don't match our asset filenames.
SPECIES_ALIAS: dict[str, str] = {
    "CROCODILE": "alligator",
}

# Test affordance: redirect the asset dir without touching sys._MEIPASS.
_asset_dir_override: Optional[str] = None

_pixmap_cache: dict[str, QPixmap] = {}


def _asset_dir() -> str:
    """Resolve assets/ccraces/ relative to repo root or PyInstaller _MEIPASS."""
    if _asset_dir_override is not None:
        return _asset_dir_override
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(base, "assets", "ccraces")


def _asset_exists(stem: str) -> bool:
    return os.path.isfile(os.path.join(_asset_dir(), f"{stem}.png"))


def asset_stem_for_species(species_name: Optional[str]) -> Optional[str]:
    """Return the asset filename stem (e.g. 'dog') for a CC species name.

    Returns None if input is None/empty, if the species is unknown, or
    if there's no matching PNG file on disk.
    """
    if not species_name:
        return None
    stem = SPECIES_ALIAS.get(species_name, species_name.lower())
    return stem if _asset_exists(stem) else None


def load_race_pixmap(stem: str) -> Optional[QPixmap]:
    """Load and cache the race PNG by stem. Returns None if missing or
    fails to load. The cache is process-wide and bounded at ~20 entries
    (one per asset), so no eviction is needed.
    """
    if not stem:
        return None
    cached = _pixmap_cache.get(stem)
    if cached is not None:
        return cached
    path = os.path.join(_asset_dir(), f"{stem}.png")
    if not os.path.isfile(path):
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    _pixmap_cache[stem] = pm
    return pm
