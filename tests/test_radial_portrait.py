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
    pm = render_account_portrait(game="ttr", toon_name=None, dna="",
                                 customizations=None, diameter=80)
    assert not pm.isNull()
    assert pm.width() == 80 and pm.height() == 80


def test_portrait_pixmap_is_requested_size():
    _app()
    from utils.overlay.radial_portrait import render_account_portrait
    pm = render_account_portrait(game="ttr", toon_name="Sir Hopper", dna="",
                                 customizations=None, diameter=96)
    assert not pm.isNull()
    assert pm.width() == 96 and pm.height() == 96


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
    pm = radial_portrait.render_account_portrait(
        game="ttr", toon_name="Sir Hopper", dna="dna-xyz",
        customizations=None, diameter=80)
    assert not pm.isNull() and pm.width() == 80
    assert calls and calls[0][0] == "dna-xyz"   # cache consulted with the toon's DNA
