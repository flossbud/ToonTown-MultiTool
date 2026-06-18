"""Regression: the Rendition portrait fetcher must verify TLS against certifi's
CA bundle, not OpenSSL's default cert paths.

On macOS (python.org framework build, PyInstaller-frozen app) the default cert
paths are frequently absent, so every HTTPS fetch died with
CERTIFICATE_VERIFY_FAILED and portraits silently never loaded. The fetcher now
passes a certifi-backed SSL context to urlopen.
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.request

import pytest

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_fetcher(monkeypatch, tmp_path):
    # IRON LAW: isolate config so the cache dir lands in a tmp dir.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    return RenditionPoseFetcher()


def test_ssl_context_is_verifying_and_uses_certifi():
    from utils.rendition_poses import _ssl_context
    ctx = _ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    # A verifying context (not the broken/None default) with CA certs loaded.
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.get_ca_certs(), "expected CA certs loaded into the context"


def test_fetch_worker_passes_verifying_context(qt_app, monkeypatch, tmp_path):
    fetcher = _make_fetcher(monkeypatch, tmp_path)
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        raise urllib.error.URLError("blocked in test")  # never touch the network

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    # _fetch_worker swallows the error and emits None; we only care about the
    # context it handed to urlopen.
    fetcher._fetch_worker("dna_for_test", "portrait")

    ctx = captured.get("context")
    assert isinstance(ctx, ssl.SSLContext), "fetcher must pass an explicit SSL context"
    assert ctx.verify_mode == ssl.CERT_REQUIRED
