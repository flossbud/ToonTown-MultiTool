"""Pattern SVG asset loader + tinting + cache.

Patterns live in `assets/patterns/<name>.svg` as single-color tiles
using `currentColor` for the fill. At render time we load the SVG,
tint it to the user's chosen color using SourceIn composition, and
cache the result keyed by (name, color hex, tile size).

Mirrors utils/cc_race_assets.py for asset path resolution.
"""

from __future__ import annotations

import os
import sys
from typing import Final, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


PATTERN_NAMES: Final = (
    "dots", "stripes_diag", "stripes_horiz", "plaid",
    "chevrons", "stars", "hearts", "waves",
)

_asset_dir_override: Optional[str] = None
_cache: dict[tuple[str, str, int], QPixmap] = {}


def _asset_dir() -> str:
    if _asset_dir_override is not None:
        return _asset_dir_override
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(base, "assets", "patterns")


def tinted_pattern_pixmap(name: str, color: QColor, tile_size: int) -> QPixmap:
    """Return a tinted pattern tile. Cached by (name, color hex, size).
    Returns an empty QPixmap for unknown names or load errors."""
    key = (name, color.name(), int(tile_size))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    if name not in PATTERN_NAMES:
        empty = QPixmap()
        _cache[key] = empty
        return empty
    svg_path = os.path.join(_asset_dir(), f"{name}.svg")
    if not os.path.isfile(svg_path):
        empty = QPixmap()
        _cache[key] = empty
        return empty
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        empty = QPixmap()
        _cache[key] = empty
        return empty
    pm = QPixmap(tile_size, tile_size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), color)
    painter.end()
    _cache[key] = pm
    return pm
