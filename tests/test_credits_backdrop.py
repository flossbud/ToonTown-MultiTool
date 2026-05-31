import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Stub:
    def get(self, key, default=None):
        return "dark" if key == "theme" else default
    def on_change(self, cb):
        pass


def _credits(qapp):
    from tabs.credits_tab import CreditsTab
    return CreditsTab(settings_manager=_Stub())


def test_credits_backdrop_source_makes_transparent(qapp):
    ct = _credits(qapp)
    pix = QPixmap(60, 40); pix.fill(Qt.blue)
    ct.set_backdrop_source(pix)
    assert ct._has_backdrop is True
    assert "transparent" in ct.styleSheet()
    assert ct._backdrop._blurred is not None
    assert not ct._backdrop.isHidden()   # setVisible(True); isVisible() needs shown ancestors


def test_credits_null_source_stays_opaque(qapp):
    ct = _credits(qapp)
    ct.set_backdrop_source(QPixmap())        # null -> no backdrop
    assert ct._has_backdrop is False
    assert "transparent" not in ct.styleSheet()
    assert ct._backdrop.isHidden()       # hidden so its 40% scrim can't dim bg_app


def test_credits_clear_backdrop_restores_bg(qapp):
    ct = _credits(qapp)
    ct.set_backdrop_source(QPixmap(60, 40))
    ct.clear_backdrop()
    assert ct._has_backdrop is False
    assert ct._backdrop._blurred is None
    assert "transparent" not in ct.styleSheet()
    assert ct._backdrop.isHidden()


def test_credits_backdrop_is_mouse_transparent_and_not_in_layout(qapp):
    ct = _credits(qapp)
    assert ct._backdrop.testAttribute(Qt.WA_TransparentForMouseEvents) is True
    assert ct._backdrop.parent() is ct
    assert ct.layout().indexOf(ct._backdrop) == -1


def test_credits_resize_tracks_backdrop(qapp):
    ct = _credits(qapp)
    ct.set_backdrop_source(QPixmap(60, 40))
    ct.show()                 # offscreen; a never-shown widget won't fire resizeEvent
    ct.resize(500, 320)
    qapp.processEvents()
    assert ct._backdrop.size() == ct.size()
    ct.hide()
