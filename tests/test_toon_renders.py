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


def _real_png(path: str, colour: str, size: int = 4) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = QImage(size, size, QImage.Format_ARGB32)
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


def test_tier_is_previous_while_a_newer_outfit_is_pending(facade):
    """The store's tier names the slot that served; the facade's names the
    user's situation. A complete look served while a newer outfit is still
    downloading IS the previous look, whichever slot holds it."""
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    store.note_dna("ttr", "Hiro", "dna2")          # candidate pending, nothing landed
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "previous" and pm.toImage().pixelColor(0, 0) == QColor("#ff0000")

    _complete(store, "ttr", "Hiro", "dna2", "#00ff00")
    pf.set_promoted.emit("ttr", "Hiro")
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "current" and pm.toImage().pixelColor(0, 0) == QColor("#00ff00")


def test_tier_returns_to_current_once_a_dead_outfit_is_dropped(facade):
    """A newer outfit the origin refuses for every pose is abandoned by the
    store, so the tooltip's "new render pending" must not stick to the toon."""
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    store.note_dna("ttr", "Hiro", "dna2")
    assert f.pixmap_for("ttr", "Hiro", "head")[1] == "previous"     # pending: tooltip case
    for pose in POSES:
        store.mark_failed("ttr", "Hiro", "dna2", pose)
    assert store.promote_if_complete("ttr", "Hiro") is False
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "current" and pm.toImage().pixelColor(0, 0) == QColor("#ff0000")
    assert store.candidate_dna("ttr", "Hiro") is None


def test_lru_is_dropped_on_promotion_so_the_new_outfit_shows(facade):
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    f.pixmap_for("ttr", "Hiro", "head")                     # cached
    _complete(store, "ttr", "Hiro", "dna2", "#00ff00")
    pf.set_promoted.emit("ttr", "Hiro")
    assert f._lru == {}                                     # old look's entry is gone
    pm, _ = f.pixmap_for("ttr", "Hiro", "head")
    assert pm.toImage().pixelColor(0, 0) == QColor("#00ff00")


def test_a_second_lookup_is_served_from_the_lru_not_the_disk(facade):
    f, store, _ = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    pm1, _ = f.pixmap_for("ttr", "Hiro", "head")
    # Same path, different pixels. Size must differ too: QPixmap(path) has its
    # own path+size decode cache (confirmed empirically) that would otherwise
    # serve this stale read all on its own within the same mtime second,
    # masking whether our _lru is doing anything at all.
    path = store.path_for("ttr", "Hiro", "dna1", "head")
    _real_png(path, "#0000ff", size=40)
    pm2, _ = f.pixmap_for("ttr", "Hiro", "head")
    assert pm2.cacheKey() == pm1.cacheKey()
    assert pm2.toImage().pixelColor(0, 0) == QColor("#ff0000")


def test_pixmap_for_never_serves_qts_own_stale_decode_after_a_same_second_rewrite(facade):
    f, store, _ = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    pm1, _ = f.pixmap_for("ttr", "Hiro", "head")
    assert pm1.toImage().pixelColor(0, 0) == QColor("#ff0000")

    f._lru.clear()                                           # what invalidate() does to us

    # Same path, same size -- the only thing that changes is the bytes. If the
    # decoder still went through QPixmap(path), Qt's own name+mtime+size cache
    # could serve the stale red pixels back here regardless of our LRU.
    path = store.path_for("ttr", "Hiro", "dna1", "head")
    _real_png(path, "#00ff00")
    pm2, _ = f.pixmap_for("ttr", "Hiro", "head")
    assert pm2.toImage().pixelColor(0, 0) == QColor("#00ff00")


def test_the_lru_holds_at_most_64_entries_and_evicts_the_oldest(qapp, tmp_path):
    # The 2-pose fixture store can't reach 64 entries; build one on the real
    # 13-pose contract so 5 toons produce 65 distinct paths.
    store = ToonRenderStore(str(tmp_path))
    pf = RenderPrefetcher(store, downloader=lambda d, p: b"", executor=_Hold())
    f = ToonRenders(store, pf)

    def _complete_all_poses(name, dna):
        store.note_dna("ttr", name, dna)
        for pose in store.poses:
            _real_png(store.path_for("ttr", name, dna, pose), "#ff0000")
            store.mark_landed("ttr", name, dna, pose)
        assert store.promote_if_complete("ttr", name)

    names = [f"Toon{i}" for i in range(5)]
    for i, name in enumerate(names):
        _complete_all_poses(name, f"dna{i}")

    first_path, _ = store.lookup("ttr", names[0], store.poses[0])
    for name in names:
        for pose in store.poses:
            f.pixmap_for("ttr", name, pose)

    assert len(f._lru) == 64
    assert first_path not in f._lru


def test_invalidate_drops_the_cached_pixmap_so_the_refetched_bytes_show(facade):
    f, store, pf = facade
    _complete(store, "ttr", "Hiro", "dna1", "#ff0000")
    pm1, tier1 = f.pixmap_for("ttr", "Hiro", "head")        # cached
    assert tier1 == "current"

    f.invalidate("ttr", "Hiro")
    assert f._lru == {}                                     # stale pixmap must not survive

    # Stand in for the download landing.
    _real_png(store.path_for("ttr", "Hiro", "dna1", "head"), "#00ff00")
    store.mark_landed("ttr", "Hiro", "dna1", "head")

    # invalidate()'s rmtree removed portrait.png too, so dna1 is an
    # incomplete candidate -- but the toon has no other set, so what has
    # re-landed is served (tier "candidate") and the refetched bytes show.
    assert store.lookup("ttr", "Hiro", "head")[1] == "candidate"
    pm2, tier2 = f.pixmap_for("ttr", "Hiro", "head")
    assert tier2 == "candidate"
    assert pm2.toImage().pixelColor(0, 0) == QColor("#00ff00")
    assert f.pixmap_for("ttr", "Hiro", "portrait") is None    # not re-landed yet


def test_a_served_candidate_passes_through_with_no_previous_look(facade):
    """The "previous while a candidate is pending" override is for a served
    *current*. A served candidate IS the pending outfit -- there is no
    previous look to warn about, so the tier (and thus the tooltip, which
    consumers show only for "previous") passes through untouched."""
    f, store, pf = facade
    store.note_dna("ttr", "Hiro", "dna1")
    _real_png(store.path_for("ttr", "Hiro", "dna1", "head"), "#00ff00")
    store.mark_landed("ttr", "Hiro", "dna1", "head")
    assert store.candidate_dna("ttr", "Hiro") == "dna1"        # the override's trigger is set
    pm, tier = f.pixmap_for("ttr", "Hiro", "head")
    assert tier == "candidate"
    assert pm.toImage().pixelColor(0, 0) == QColor("#00ff00")
    assert pf.pending_count + pf.in_flight_count == 0          # a hit: nothing wanted


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


def test_make_default_stamps_the_cache_root_and_breaker_transitions(qapp, tmp_path, capsys):
    """Running-code proof: a live validation begins by confirming the stamp,
    and every breaker transition is stamped the same way."""
    from utils.toon_renders import make_default
    root = str(tmp_path / "rc")
    f = make_default(root)
    try:
        f.prefetcher.breaker_changed.emit(True)
        f.prefetcher.breaker_changed.emit(False)
        out = capsys.readouterr().out
        assert f"[ToonRenders] cache root {root}" in out
        assert "[ToonRenders] breaker open" in out
        assert "[ToonRenders] breaker closed" in out
        assert out.index("breaker open") < out.index("breaker closed")
    finally:
        f.prefetcher._executor.shutdown(wait=False)


def test_tooltip_constant():
    assert PREVIOUS_LOOK_TOOLTIP == "Showing previous look — new render pending."
