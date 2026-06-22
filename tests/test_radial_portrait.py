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
