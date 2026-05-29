"""Tests for the Corporate Clash game-file patcher."""

import gzip
import hashlib
import os
import subprocess
import threading

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import services.cc_patcher as p


def _qapp():
    return QApplication.instance() or QApplication([])


def test_platform_for_os():
    assert p._platform_for_os(plat="linux") == "windows"
    assert p._platform_for_os(plat="win32") == "windows"
    assert p._platform_for_os(plat="darwin") == "macos"


def test_fetch_all_manifests_merges_and_tags_platform(monkeypatch):
    win = {"files": [{"fileName": "a.dll", "filePath": "a.dll",
                      "sha1": "h1", "compressed_sha1": "c1"}]}
    res = {"files": [{"fileName": "g.prc", "filePath": "config\\g.prc",
                      "sha1": "h2", "compressed_sha1": "c2"}]}

    def fake_get(url, **k):
        class R:
            def raise_for_status(self): pass
            def json(self): return win if url.endswith("/windows") else res
        return R()

    monkeypatch.setattr(p.requests, "get", fake_get)
    files = p.fetch_all_manifests("production", "windows")
    by_path = {f["filePath"]: f for f in files}
    assert by_path["a.dll"]["_platform"] == "windows"
    assert by_path["config\\g.prc"]["_platform"] == "resources"
    assert len(files) == 2


def test_download_name_hashes_raw_filepath_plus_token():
    expected = hashlib.sha1(("config\\g.prc" + "resources").encode("utf-8"),
                            usedforsecurity=False).hexdigest()
    assert p.download_name("config\\g.prc", "resources") == expected


def test_fetch_verified_roundtrip_and_mismatches(monkeypatch):
    raw = b"corporate-clash-file"
    comp = gzip.compress(raw)
    entry = {
        "filePath": "config\\g.prc",
        "sha1": hashlib.sha1(raw, usedforsecurity=False).hexdigest(),
        "compressed_sha1": hashlib.sha1(comp, usedforsecurity=False).hexdigest(),
        "_platform": "resources",
    }
    seen = {}

    class R:
        status_code = 200
        content = comp
        def raise_for_status(self): pass

    def fake_get(url, **k):
        seen["url"] = url
        return R()

    monkeypatch.setattr(p.requests, "get", fake_get)
    assert p.fetch_verified(entry, "https://dl/base") == raw
    assert seen["url"] == "https://dl/base/" + p.download_name("config\\g.prc", "resources")

    with pytest.raises(ValueError):
        p.fetch_verified(dict(entry, compressed_sha1="00"), "https://dl/base")
    with pytest.raises(ValueError):
        p.fetch_verified(dict(entry, sha1="00"), "https://dl/base")


def test_resolve_download_base_reads_metadata(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"downloadservers": [{"id": 1, "base_url": "https://dl/one",
                                         "realm": "production"}]}
    monkeypatch.setattr(p.requests, "get", lambda url, **k: R())
    assert p.resolve_download_base("tok", "production") == "https://dl/one"


def test_resolve_download_base_raises_without_server(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"downloadservers": []}
    monkeypatch.setattr(p.requests, "get", lambda url, **k: R())
    with pytest.raises(ValueError):
        p.resolve_download_base("tok", "production")
