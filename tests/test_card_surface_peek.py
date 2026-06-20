# tests/test_card_surface_peek.py
import sys
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from utils.overlay.surface import CardSurface


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def test_set_peek_tracks_flag(qt_app):
    # set_peek is now a pure state flag; the body-dim rendering is driven by the
    # controller through the card provider (it owns and dims the body widgets).
    s = CardSurface(surface_id=0)
    s.host(QLabel("card"), base_size=(120, 90))
    s.show()
    qt_app.processEvents()
    assert s.is_peeking is False
    s.set_peek(True)
    assert s.is_peeking is True
    s.set_peek(False)
    assert s.is_peeking is False
    s.release()


def test_set_content_opacity_dims_the_proxy(qt_app):
    s = CardSurface(surface_id=0)
    s.host(QLabel("card"), base_size=(120, 90))
    s.show()
    qt_app.processEvents()
    s.set_content_opacity(0.8)
    assert s._scaled_view._proxy.opacity() == pytest.approx(0.8)
    s.set_content_opacity(1.0)
    assert s._scaled_view._proxy.opacity() == pytest.approx(1.0)
    s.release()
