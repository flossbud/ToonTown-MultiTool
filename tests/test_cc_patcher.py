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
