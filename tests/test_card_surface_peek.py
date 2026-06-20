# tests/test_card_surface_peek.py
import sys
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QLabel
from utils.overlay.surface import CardSurface


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def _card():
    w = QLabel("card")
    w.setFixedSize(120, 90)
    return w


def test_set_peek_immediate_dims_body_and_clears(qt_app):
    s = CardSurface(surface_id=0)
    s.host(_card(), base_size=(120, 90))
    s.show()
    qt_app.processEvents()

    s.set_peek(True, [QRect(4, 4, 20, 20)], animate=False)
    assert s.is_peeking is True
    assert s._scaled_view.peek_opacity() == pytest.approx(0.75, abs=0.01)

    s.set_peek(False, None, animate=False)
    assert s.is_peeking is False
    assert s._scaled_view.peek_opacity() == pytest.approx(1.0, abs=0.01)
    s.release()


def test_set_peek_failclosed_on_render_error_stays_opaque(qt_app, monkeypatch):
    s = CardSurface(surface_id=0)
    s.host(_card(), base_size=(120, 90))
    s.show()
    qt_app.processEvents()
    # Force the overlay build to raise; the card must end fully opaque, not stuck.
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")   # fail the dim attempt
        # the fail-closed restore call (opacity 1.0) is allowed through

    monkeypatch.setattr(s._scaled_view, "set_peek_opacity", boom)
    s.set_peek(True, [QRect(4, 4, 20, 20)], animate=False)
    # fail-closed: it attempted the dim, then the restore to 1.0 (two calls)
    assert calls["n"] >= 2
    s.release()
