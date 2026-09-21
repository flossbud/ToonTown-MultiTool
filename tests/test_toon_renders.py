"""The consumer facade: sync pixmaps from disk, LRU invalidation on promotion."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor, QImage, QPixmap

from utils.render_prefetcher import RenderPrefetcher
from utils.toon_render_store import ToonRenderStore
from utils.toon_renders import PREVIOUS_LOOK_TOOLTIP, ToonRenders

POSES = ("portrait", "head")


def _real_png(path: str, colour: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(QColor(colour))
    assert img.save(path, "PNG")


class _Hold:
    """Accepts work and never runs it, so queued/in-flight counts are observable."""
    def submit(self, fn, *a):
        from concurrent.futures import Future
        return Future()


@pytest.fixture
def facade(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    pf = RenderPrefetcher(store, downloader=lambda d, p: b"", executor=_Hold())
    f = ToonRenders(store, pf)
    ToonRenders.install_for_tests(f)
    yield f, store, pf
    ToonRenders.install_for_tests(None)


def _complete(store, game, name, dna, colour):
    store.note_dna(game, name, dna)
    for pose in POSES:
        _real_png(store.path_for(game, name, dna, pose), colour)
        store.mark_landed(game, name, dna, pose)
    assert store.promote_if_complete(game, name)


def test_nothing_cached_returns_none(facade):
    f, *_ = facade
    assert f.pixmap_for("ttr", "Nobody", "head") is None


def test_current_set_serves_with_tier_current(facade):
    f, store, _ = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "current" and pm.toImage().pixelColor(0, 0) == QColor("#ff0000")


def test_previous_set_serves_with_tier_previous(facade):
    f, store, _ = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    _complete(store, "ttr", "Hiro", "dna2", "#00ff00")
    os.remove(store.path_for("ttr", "Hiro", "dna2", "head"))
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "previous" and pm.toImage().pixelColor(0, 0) == QColor("#ff0000")


def test_lru_is_dropped_on_promotion_so_the_new_outfit_shows(facade):
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    f.pixmap_for("ttr", "Hiro", "head")                     # cached
    _complete(store, "ttr", "Hiro", "dna2", "#00ff00")
    pf.set_promoted.emit("ttr", "Hiro")
    pm, _ = f.pixmap_for("ttr", "Hiro", "head")
    assert pm.toImage().pixelColor(0, 0) == QColor("#00ff00")


def test_an_undecodable_file_reads_as_none_and_is_wanted(facade):
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    with open(store.path_for("ttr", "Hiro", "dna1", "head"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\ngarbage")            # signature ok, body not
    assert f.pixmap_for("ttr", "Hiro", "head") is None
    assert pf.pending_count + pf.in_flight_count >= 1     # queued for re-download


def test_instance_is_a_singleton_and_tests_can_replace_it(facade):
    f, *_ = facade
    assert ToonRenders.instance() is f


def test_tooltip_constant():
    assert PREVIOUS_LOOK_TOOLTIP == "Showing previous look — new render pending."
