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


def test_pose_pulled_synchronously_from_disk_cache(monkeypatch):
    # The toon image must come from the SYNC disk cache (set_dna's fetch is async,
    # so without this the grab captures only the background). Verify the cache is
    # consulted with the toon's (dna, resolved pose) and the result is applied.
    _app()
    from PySide6.QtGui import QPixmap
    from utils.rendition_poses import RenditionPoseFetcher
    from utils.overlay import radial_portrait

    calls = []
    swatch = QPixmap(64, 64)
    swatch.fill()  # opaque, non-null

    def fake_cached(self, dna, pose):
        calls.append((dna, pose))
        return swatch

    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap", fake_cached, raising=True)
    r = radial_portrait.render_account_portrait(
        game="ttr", toon_name="Sir Hopper", dna="dna-xyz",
        customizations=None, diameter=80)
    assert not r.pixmap.isNull() and r.pixmap.width() == 80
    assert calls and calls[0][0] == "dna-xyz"   # cache consulted with the toon's DNA


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


def test_status_pending_on_cache_miss(monkeypatch):
    _app()
    from utils.rendition_poses import RenditionPoseFetcher
    from utils.overlay.radial_portrait import render_account_portrait
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None, raising=True)
    # Stub the async fetch so set_dna's request side-effect does not hit the
    # real Rendition server (offline-flaky + leaks a pool task otherwise).
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None, raising=True)
    r = render_account_portrait(game="ttr", toon_name="Sir Hopper",
                                dna="dna-xyz", customizations=None, diameter=80)
    assert r.status == "pending"


def test_status_complete_on_cache_hit(monkeypatch):
    _app()
    from PySide6.QtGui import QPixmap
    from utils.rendition_poses import RenditionPoseFetcher
    from utils.overlay.radial_portrait import render_account_portrait
    swatch = QPixmap(64, 64); swatch.fill()
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: swatch, raising=True)
    r = render_account_portrait(game="ttr", toon_name="Sir Hopper",
                                dna="dna-xyz", customizations=None, diameter=80)
    assert r.status == "complete"


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
