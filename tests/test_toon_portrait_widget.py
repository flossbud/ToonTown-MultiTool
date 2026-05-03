import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _image(color="#ff0000"):
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


def test_portrait_ready_accepts_decoded_qimage(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget

    badge = ToonPortraitWidget(1)
    badge._dna = "toon-dna"
    badge._fetch_token = 7
    badge._loading = True

    badge._on_image_ready("toon-dna|7", _image())

    assert badge._loading is False
    assert badge._pixmap is not None
    assert not badge._pixmap.isNull()


def test_portrait_ready_ignores_stale_token(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget

    badge = ToonPortraitWidget(1)
    badge._dna = "new-dna"
    badge._fetch_token = 2
    badge._loading = True

    badge._on_image_ready("old-dna|1", _image())

    assert badge._loading is True
    assert badge._pixmap is None


def test_set_dna_does_not_cancel_matching_inflight_fetch(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget

    badge = ToonPortraitWidget(1)
    badge._dna = "toon-dna"
    badge._fetch_token = 4
    badge._loading = True

    badge.set_dna("toon-dna")

    assert badge._fetch_token == 4
    badge._on_image_ready("toon-dna|4", _image())
    assert badge._pixmap is not None
    assert not badge._pixmap.isNull()


def test_portrait_fetch_emits_decoded_image(monkeypatch, qapp):
    from tabs.multitoon._tab import ToonPortraitWidget

    png = QImage(4, 4, QImage.Format_ARGB32)
    png.fill(QColor("#00ff00"))

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert png.save(buffer, "PNG")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return bytes(data)

    def _urlopen(_request, timeout=10):
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    badge = ToonPortraitWidget(1)
    badge._dna = "toon-dna"
    badge._fetch_token = 3
    badge._fetch("toon-dna", 3)

    assert badge._pixmap is not None
    assert not badge._pixmap.isNull()
