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
