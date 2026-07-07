"""Paint a tinted race silhouette (mask-and-fill of assets/ccraces/*.png).

Shared by the Launch primary-toon slot and picker rows. Composites on an
ARGB32_Premultiplied QImage so a fully-opaque source can't drop its alpha
(the DestinationIn-no-op trap). Fill = the given accent color.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from utils import cc_race_assets


def paint_race_silhouette(painter: QPainter, rect: QRect, species: str | None,
                          accent: str) -> bool:
    """Fill the species mask with `accent` into `rect`. Returns False (paints
    nothing) when the species/asset is unavailable."""
    stem = cc_race_assets.asset_stem_for_species(species)
    if not stem:
        return False
    mask = cc_race_assets.load_race_pixmap(stem)
    if mask is None or mask.isNull():
        return False
    side = min(rect.width(), rect.height())
    if side <= 0:
        return False
    tmp = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    tmp.fill(0)
    tp = QPainter(tmp)
    tp.setRenderHint(QPainter.Antialiasing, True)
    tp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    tp.fillRect(0, 0, side, side, QColor(accent))
    tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    scaled = mask.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    dx = (side - scaled.width()) // 2
    dy = (side - scaled.height()) // 2
    tp.drawPixmap(dx, dy, scaled)
    tp.end()
    painter.drawImage(rect.x() + (rect.width() - side) // 2,
                      rect.y() + (rect.height() - side) // 2,
                      tmp)
    return True
