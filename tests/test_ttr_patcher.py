"""Tests for the TTR game-file patcher."""

import bz2
import hashlib
import os
import threading

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import services.ttr_patcher as p


def _qapp():
    return QApplication.instance() or QApplication([])


def test_applicable_filters_by_platform(monkeypatch):
    monkeypatch.setattr(p, "_platform_tokens", lambda: {"linux"})
    assert p._applicable({"only": ["linux", "win64"]}) is True
    assert p._applicable({}) is True            # no 'only' -> all platforms
    assert p._applicable({"only": ["darwin"]}) is False


def test_local_sha1_streams_and_handles_missing(tmp_path):
    f = tmp_path / "x.mf"
    f.write_bytes(b"hello")
    assert p.local_sha1(str(f)) == hashlib.sha1(b"hello", usedforsecurity=False).hexdigest()
    assert p.local_sha1(str(tmp_path / "nope.mf")) is None


def test_select_stale_detects_mismatch_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "_platform_tokens", lambda: {"linux"})
    (tmp_path / "phase_ok.mf").write_bytes(b"hello")
    (tmp_path / "phase_bad.mf").write_bytes(b"different")
    manifest = {
        "phase_ok.mf":   {"hash": hashlib.sha1(b"hello", usedforsecurity=False).hexdigest(), "only": ["linux"]},
        "phase_bad.mf":  {"hash": "deadbeef", "only": ["linux"]},
        "phase_gone.mf": {"hash": "cafef00d", "only": ["linux"]},
        "mac_only.mf":   {"hash": "whatever", "only": ["darwin"]},
        "no_hash.mf":    {"only": ["linux"]},
    }
    stale = dict(p.select_stale(manifest, str(tmp_path)))
    assert set(stale) == {"phase_bad.mf", "phase_gone.mf"}


def test_resolve_mirror_uses_first_endpoint(monkeypatch):
    class R:
        def __init__(self, data): self._d = data
        def raise_for_status(self): pass
        def json(self): return self._d
    monkeypatch.setattr(p.requests, "get",
                        lambda url, **k: R(["https://m1/patches/"]))
    assert p.resolve_mirror() == "https://m1/patches/"


def test_resolve_mirror_falls_back_when_all_fail(monkeypatch):
    def boom(url, **k):
        raise p.requests.RequestException("down")
    monkeypatch.setattr(p.requests, "get", boom)
    assert p.resolve_mirror() == p._FALLBACK_MIRROR


def test_fetch_verified_roundtrip_and_mismatches(monkeypatch):
    raw = b"phase-file-contents"
    comp = bz2.compress(raw)
    entry = {
        "dl": "phase_x.mf.abc.bz2",
        "hash": hashlib.sha1(raw, usedforsecurity=False).hexdigest(),
        "compHash": hashlib.sha1(comp, usedforsecurity=False).hexdigest(),
    }

    class R:
        content = comp
        def raise_for_status(self): pass

    monkeypatch.setattr(p.requests, "get", lambda url, **k: R())
    assert p.fetch_verified(entry, "https://m/patches/") == raw

    with pytest.raises(ValueError):
        p.fetch_verified(dict(entry, compHash="00"), "https://m/patches/")
    with pytest.raises(ValueError):
        p.fetch_verified(dict(entry, hash="00"), "https://m/patches/")


def test_fetch_verified_normalizes_mirror_without_trailing_slash(monkeypatch):
    raw = b"x"
    comp = bz2.compress(raw)
    entry = {
        "dl": "p.bz2",
        "hash": hashlib.sha1(raw, usedforsecurity=False).hexdigest(),
        "compHash": hashlib.sha1(comp, usedforsecurity=False).hexdigest(),
    }
    seen = {}

    class R:
        content = comp
        def raise_for_status(self): pass

    def fake_get(url, **k):
        seen["url"] = url
        return R()

    monkeypatch.setattr(p.requests, "get", fake_get)
    # mirror WITHOUT trailing slash must still produce …/patches/p.bz2
    assert p.fetch_verified(entry, "https://m/patches") == raw
    assert seen["url"] == "https://m/patches/p.bz2"


def test_fetch_verified_rejects_entry_missing_fields():
    with pytest.raises(ValueError):
        p.fetch_verified({"dl": "p.bz2", "hash": "h"}, "https://m/")  # no compHash
