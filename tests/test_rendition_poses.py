"""Tests for RenditionPoseFetcher: disk cache + async fetch + paint-race guards."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    # Reset the singleton between tests.
    from utils import rendition_poses
    rendition_poses.RenditionPoseFetcher._instance = None
    yield tmp_path
    rendition_poses.RenditionPoseFetcher._instance = None


def test_url_template_uses_512_resolution():
    from utils.rendition_poses import _URL
    assert "/512x512.png" in _URL
    assert "/128x128" not in _URL


def test_request_size_constant_is_512():
    from utils.rendition_poses import _REQUEST_SIZE
    assert _REQUEST_SIZE == 512


def test_pose_names_tuple_has_13_entries():
    from utils.rendition_poses import POSE_NAMES
    assert isinstance(POSE_NAMES, tuple)
    assert len(POSE_NAMES) == 13
    # Spot-check the canonical first + last + a portrait-variant.
    assert POSE_NAMES[0] == "portrait"
    assert "portrait-grin" in POSE_NAMES
    assert "laffmeter" in POSE_NAMES


def test_cache_dir_under_config_dir(qapp, isolated_cache):
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    cache = fetcher.cache_dir()
    assert cache == os.path.join(str(isolated_cache), "rendition_cache")
    assert os.path.isdir(cache)


def test_cached_pixmap_returns_none_for_missing(qapp, isolated_cache):
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    assert fetcher.cached_pixmap("dna123", "portrait") is None


def test_cached_pixmap_returns_pixmap_for_fresh_disk_entry(qapp, isolated_cache):
    """A pre-existing fresh PNG in the cache dir should be readable."""
    from utils.rendition_poses import RenditionPoseFetcher
    # Build a 2x2 red PNG and drop it in the cache.
    from PySide6.QtGui import QImage, QColor
    img = QImage(2, 2, QImage.Format_ARGB32)
    img.fill(QColor("#ff0000"))
    fetcher = RenditionPoseFetcher.instance()
    path = fetcher._path_for("dna123", "portrait")
    img.save(path, "PNG")

    pm = fetcher.cached_pixmap("dna123", "portrait")
    assert pm is not None
    assert not pm.isNull()
    assert pm.width() == 2


def test_cached_pixmap_returns_none_for_stale_entry(qapp, isolated_cache):
    """Older than TTL -> cached_pixmap returns None (caller will refetch)."""
    import time
    from PySide6.QtGui import QImage, QColor
    from utils.rendition_poses import RenditionPoseFetcher, _TTL_SECONDS
    fetcher = RenditionPoseFetcher.instance()
    path = fetcher._path_for("dna123", "head")
    img = QImage(2, 2, QImage.Format_ARGB32)
    img.fill(QColor("#00ff00"))
    img.save(path, "PNG")
    # Set mtime to longer than TTL ago.
    old = time.time() - _TTL_SECONDS - 60
    os.utime(path, (old, old))

    assert fetcher.cached_pixmap("dna123", "head") is None


def test_request_emits_pose_ready_for_fresh_disk_entry(qapp, isolated_cache):
    """If the disk cache is fresh, request() should NOT hit the network -
    it should emit pose_ready with the cached pixmap immediately."""
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtGui import QImage, QColor
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    path = fetcher._path_for("dna123", "waving")
    img = QImage(2, 2, QImage.Format_ARGB32)
    img.fill(QColor("#0000ff"))
    img.save(path, "PNG")

    spy = QSignalSpy(fetcher.pose_ready)
    fetcher.request("dna123", "waving")
    # Drain Qt events: the fetcher routes the synchronous cache hit
    # through a 0 ms QTimer.singleShot so all consumers see the same
    # GUI-thread signal pattern.
    for _ in range(5):
        qapp.processEvents()
    assert spy.count() == 1
    payload = spy.at(0)
    assert payload[0] == "dna123"
    assert payload[1] == "waving"
    assert payload[2] is not None and not payload[2].isNull()


def test_request_fetches_when_cache_miss(qapp, isolated_cache, monkeypatch):
    """Cache miss -> urlopen() is invoked, bytes are written to disk,
    pose_ready emitted with a QPixmap on the GUI thread."""
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtGui import QImage, QColor
    from utils.rendition_poses import RenditionPoseFetcher

    # Synthesize a PNG byte stream the worker can return.
    img = QImage(3, 3, QImage.Format_ARGB32)
    img.fill(QColor("#abcdef"))
    from PySide6.QtCore import QBuffer, QIODevice, QByteArray
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    png_bytes = bytes(ba)
    buf.close()

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return self._payload

    captured_urls = []

    def _fake_urlopen(request, timeout=10):
        captured_urls.append(request.full_url if hasattr(request, "full_url") else str(request))
        return _FakeResponse(png_bytes)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    fetcher = RenditionPoseFetcher.instance()
    spy = QSignalSpy(fetcher.pose_ready)
    fetcher.request("dnaXYZ", "portrait-grin")

    # Worker thread -> private signal -> GUI-thread decode -> public emit.
    # Poll up to ~2 seconds.
    import time
    deadline = time.time() + 2.0
    while time.time() < deadline and spy.count() == 0:
        qapp.processEvents()
        time.sleep(0.02)

    assert spy.count() == 1, "pose_ready should have fired once"
    payload = spy.at(0)
    assert payload[0] == "dnaXYZ"
    assert payload[1] == "portrait-grin"
    assert payload[2] is not None and not payload[2].isNull()
    # urlopen captured a URL containing the requested pose name.
    assert any("portrait-grin" in u for u in captured_urls)
    # Bytes landed on disk.
    expected_path = fetcher._path_for("dnaXYZ", "portrait-grin")
    assert os.path.isfile(expected_path)


def test_request_emits_none_on_http_failure(qapp, isolated_cache, monkeypatch):
    from PySide6.QtTest import QSignalSpy
    from utils.rendition_poses import RenditionPoseFetcher

    def _broken_urlopen(request, timeout=10):
        raise OSError("simulated network error")

    monkeypatch.setattr("urllib.request.urlopen", _broken_urlopen)

    fetcher = RenditionPoseFetcher.instance()
    spy = QSignalSpy(fetcher.pose_ready)
    fetcher.request("dnaXYZ", "portrait")

    import time
    deadline = time.time() + 2.0
    while time.time() < deadline and spy.count() == 0:
        qapp.processEvents()
        time.sleep(0.02)

    assert spy.count() == 1
    assert spy.at(0)[2] is None


def test_invalidate_dna_removes_matching_files(qapp, isolated_cache):
    from PySide6.QtGui import QImage, QColor
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    for pose in ("portrait", "head", "waving"):
        img = QImage(1, 1, QImage.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        img.save(fetcher._path_for("dnaABC", pose), "PNG")
    # Different DNA should NOT be touched.
    img.save(fetcher._path_for("otherDNA", "portrait"), "PNG")

    fetcher.invalidate_dna("dnaABC")

    files = set(os.listdir(fetcher.cache_dir()))
    assert "otherDNA__portrait.png" in files
    assert not any(f.startswith("dnaABC__") for f in files)


def test_max_workers_is_three_or_fewer(qapp, isolated_cache):
    """Regression: workers must stay capped so the dialog-open burst
    doesn't reintroduce the Python 3.14 paint-time GC race."""
    from utils.rendition_poses import RenditionPoseFetcher
    fetcher = RenditionPoseFetcher.instance()
    # ThreadPoolExecutor exposes _max_workers (private but stable across
    # 3.10-3.14). Using it here is intentional - this test exists to
    # catch refactors that bump the constant.
    assert fetcher._executor._max_workers <= 3


def test_worker_emits_bytes_not_qimage(qapp, isolated_cache, monkeypatch):
    """Regression: the private _bytes_ready signal must carry `bytes`
    (or None), NOT a QImage/QPixmap. Worker threads must do zero Qt
    object construction - see docs/postmortem-py314-gc-paint-segv.md."""
    from PySide6.QtTest import QSignalSpy
    from utils.rendition_poses import RenditionPoseFetcher

    # Provide a tiny PNG payload.
    from PySide6.QtCore import QBuffer, QIODevice, QByteArray
    from PySide6.QtGui import QImage, QColor
    img = QImage(1, 1, QImage.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    png_bytes = bytes(ba)

    class _FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return png_bytes

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=10: _FakeResponse()
    )

    fetcher = RenditionPoseFetcher.instance()
    spy = QSignalSpy(fetcher._bytes_ready)
    fetcher.request("dnaTEST", "portrait")

    import time
    deadline = time.time() + 2.0
    while time.time() < deadline and spy.count() == 0:
        qapp.processEvents()
        time.sleep(0.02)

    assert spy.count() == 1
    payload = spy.at(0)[2]
    # Must be raw bytes or None, never a Qt object.
    assert payload is None or isinstance(payload, (bytes, bytearray))
