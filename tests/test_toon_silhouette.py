"""paint_race_silhouette - mask-and-fill a race PNG with an arbitrary color."""
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import QRect

from utils.toon_silhouette import paint_race_silhouette


def _render(species, accent, size=38):
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    painted = paint_race_silhouette(p, QRect(0, 0, size, size), species, accent)
    p.end()
    return painted, img


def test_known_species_paints_nonempty(qapp):
    painted, img = _render("DOG", "#8ab6f0")
    assert painted is True
    assert any(QColor(img.pixel(x, y)).alpha() > 0
               for x in range(0, 38, 3) for y in range(0, 38, 3))


def test_unknown_species_returns_false(qapp):
    painted, img = _render("NOTASPECIES", "#8ab6f0")
    assert painted is False


def test_none_species_returns_false(qapp):
    painted, _ = _render(None, "#8ab6f0")
    assert painted is False
