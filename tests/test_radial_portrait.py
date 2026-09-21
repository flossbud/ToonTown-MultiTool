import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="run under QT_QPA_PLATFORM=offscreen",
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_placeholder_pixmap_when_no_toon():
    _app()
    from utils.overlay.radial_portrait import render_account_portrait
    r = render_account_portrait(game="ttr", toon_name=None, dna="",
                                customizations=None, diameter=80)
    assert not r.pixmap.isNull()
    assert r.pixmap.width() == 80 and r.pixmap.height() == 80


def test_portrait_pixmap_is_requested_size():
    _app()
    from utils.overlay.radial_portrait import render_account_portrait
    r = render_account_portrait(game="ttr", toon_name="Sir Hopper", dna="",
                                customizations=None, diameter=96)
    assert not r.pixmap.isNull()
    assert r.pixmap.width() == 96 and r.pixmap.height() == 96


def test_status_no_pose_when_no_toon():
    _app()
    from utils.overlay.radial_portrait import render_account_portrait
    r = render_account_portrait(game="ttr", toon_name=None, dna="",
                                customizations=None, diameter=80)
    assert r.status == "no_pose"
    assert not r.pixmap.isNull() and r.pixmap.width() == 80


def test_status_no_pose_when_empty_dna():
    _app()
    from utils.overlay.radial_portrait import render_account_portrait
    r = render_account_portrait(game="ttr", toon_name="Sir Hopper", dna="",
                                customizations=None, diameter=80)
    assert r.status == "no_pose"


def test_render_account_portrait_is_complete_from_disk(render_cache, qapp):
    from utils.overlay.radial_portrait import render_account_portrait
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    r = render_account_portrait("ttr", "Hiro", "dna1", None, 64)
    assert r.status == "complete"
    r2 = render_account_portrait("ttr", "Nobody", "dnaX", None, 64)
    assert r2.status == "no_pose"


def test_nothing_on_disk_is_no_pose_until_a_set_lands(render_cache, qapp):
    """The cache path never reports "pending": a miss is "no_pose" (the
    ring's fallback, no spinner - a permanently failing download would
    otherwise spin the ring forever), and once a set is on disk a
    re-render is "complete"."""
    from utils.overlay.radial_portrait import render_account_portrait
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    store.note_dna("ttr", "Hiro", "dna1")           # discovered, nothing landed
    r = render_account_portrait("ttr", "Hiro", "dna1", None, 64)
    assert r.status == "no_pose"
    complete_set(store, "ttr", "Hiro", "dna1")
    r = render_account_portrait("ttr", "Hiro", "dna1", None, 64)
    assert r.status == "complete"


def test_render_account_portrait_grabs_the_cached_pose(render_cache):
    """The grab must show the toon's cached render, not just the widget's
    background: the disc centre carries the pose's colour."""
    from utils.overlay.radial_portrait import render_account_portrait
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    r = render_account_portrait("ttr", "Hiro", "dna1", None, 80)
    assert not r.pixmap.isNull() and r.pixmap.width() == 80
    c = r.pixmap.toImage().pixelColor(40, 40)
    assert c.red() > 200 and c.green() < 60 and c.blue() < 60, c.getRgb()


def test_render_account_portrait_survives_a_cache_failure(render_cache, monkeypatch):
    """A cache failure must never break the overlay: the render still
    returns a full-size disc, reported as "no_pose" (never "pending": the
    ring must not spin on a cache it cannot read)."""
    from utils.overlay.radial_portrait import render_account_portrait
    facade, store, pf = render_cache

    def _boom(*a, **k):
        raise RuntimeError("cache exploded")

    monkeypatch.setattr(facade, "pixmap_for", _boom)
    monkeypatch.setattr(facade, "discovered", _boom)
    r = render_account_portrait("ttr", "Hiro", "dna1", None, 64)
    assert r.status == "no_pose"
    assert not r.pixmap.isNull() and r.pixmap.width() == 64


def test_circular_normalizes_dpr_backed_sources(qapp):
    """QWidget.grab() returns a dpr-BACKED pixmap on HiDPI screens; the
    portrait pipeline is LOGICAL-ONLY (consumers compare/blit by pm.width()
    == diameter). Unnormalized, scaled() works in physical px and the result
    inherits the dpr - the accounts ring painted portraits at HALF the disc
    size on the Retina laptop (2026-07-05). _circular must return a plain
    dpr-1.0 pixmap whose content FILLS the disc."""
    from PySide6.QtGui import QColor, QPixmap
    from utils.overlay.radial_portrait import _circular

    src = QPixmap(128, 128)
    src.fill(QColor(255, 0, 0))
    src.setDevicePixelRatio(2.0)          # what grab() returns on Retina

    out = _circular(src, 90)

    assert out.width() == 90 and out.height() == 90
    assert out.devicePixelRatio() == 1.0
    img = out.toImage()
    # With the dpr bug the content covered only the top-left quadrant,
    # leaving the disc's right half transparent.
    probe = img.pixelColor(80, 45)
    assert probe.alpha() > 0 and probe.red() > 200
