"""Helpers for tests that need a toon's renders on disk without any network."""
import os

from PySide6.QtGui import QColor, QImage


def real_png(path: str, colour: str = "#4a8fe7") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(colour))
    assert img.save(path, "PNG"), path


def complete_set(store, game: str, name: str, dna: str, colour: str = "#4a8fe7",
                 poses=None) -> None:
    """Land every pose for `dna` and promote it to the toon's current set."""
    store.note_dna(game, name, dna)
    for pose in (poses or store.poses):
        real_png(store.path_for(game, name, dna, pose), colour)
        assert store.mark_landed(game, name, dna, pose)
    assert store.promote_if_complete(game, name)
