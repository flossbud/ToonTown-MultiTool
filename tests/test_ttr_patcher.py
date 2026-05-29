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
