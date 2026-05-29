"""Tests for the TTR game-file patcher."""

import bz2
import hashlib
import os
import subprocess
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


def test_place_file_non_flatpak_atomic_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: False)
    dest = tmp_path / "phase_14.mf"
    dest.write_bytes(b"old")
    p.place_file(b"new-bytes", str(dest))
    assert dest.read_bytes() == b"new-bytes"
    # no leftover temp files
    assert [f for f in os.listdir(tmp_path) if f.endswith(".ttmt.tmp")] == []


def test_place_file_flatpak_stages_and_host_moves(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: True)
    staging = tmp_path / "stage"
    staging.mkdir()
    monkeypatch.setattr(p, "host_visible_cache_dir", lambda name: str(staging))

    calls = []
    captured = {}

    def fake_host_run(argv, **kw):
        argv = list(argv)
        calls.append(argv)
        if argv[0] == "cp":
            captured["staged_bytes"] = open(argv[-2], "rb").read()  # cp -- <staged> <tmp>
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(p, "host_run", fake_host_run)

    dest = "/host/ttr/data/phase_14.mf"
    p.place_file(b"verified", dest)

    assert captured["staged_bytes"] == b"verified"
    assert calls[0][0] == "cp" and calls[0][-1] == dest + ".ttmt.tmp"
    assert calls[1][:2] == ["mv", "-f"] and calls[1][-1] == dest
    # never wrote directly to the read-only dest dir in-sandbox
    assert not os.path.exists(dest)
    # staged file is cleaned up
    assert not os.path.exists(os.path.join(str(staging), "phase_14.mf"))


def test_place_file_flatpak_cleans_temp_when_mv_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: True)
    staging = tmp_path / "stage"
    staging.mkdir()
    monkeypatch.setattr(p, "host_visible_cache_dir", lambda name: str(staging))

    calls = []

    def fake_host_run(argv, **kw):
        argv = list(argv)
        calls.append(argv)
        if argv[0] == "mv":
            raise subprocess.CalledProcessError(1, argv)
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(p, "host_run", fake_host_run)

    dest = "/host/ttr/data/phase_14.mf"
    with pytest.raises(subprocess.CalledProcessError):
        p.place_file(b"verified", dest)

    # staged file cleaned up despite the failure
    assert not os.path.exists(os.path.join(str(staging), "phase_14.mf"))
    # best-effort rm of the orphaned game-dir temp was attempted
    assert any(c[0] == "rm" and c[-1] == dest + ".ttmt.tmp" for c in calls)


def test_place_file_non_flatpak_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: False)
    dest = tmp_path / "phase_14.mf"
    dest.write_bytes(b"old")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(p.os, "replace", boom)
    with pytest.raises(OSError):
        p.place_file(b"new", str(dest))

    assert dest.read_bytes() == b"old"   # dest untouched
    assert [f for f in os.listdir(tmp_path) if f.endswith(".ttmt.tmp")] == []  # temp cleaned


def _run_patch(monkeypatch, **stubs):
    """Drive TTRPatcher.verify_and_patch and return the terminal result dict."""
    _qapp()
    p.reset_verify_cache()
    for name, val in stubs.items():
        monkeypatch.setattr(p, name, val)
    patcher = p.TTRPatcher()
    done = threading.Event()
    result = {}
    patcher.up_to_date.connect(lambda: (result.update(kind="up_to_date"), done.set()), Qt.DirectConnection)
    patcher.patched.connect(lambda files: (result.update(kind="patched", files=files), done.set()), Qt.DirectConnection)
    patcher.failed.connect(lambda msg: (result.update(kind="failed", msg=msg), done.set()), Qt.DirectConnection)
    patcher.verify_and_patch("/engine")
    assert done.wait(2.0), "no terminal signal"
    return result, patcher


def test_verify_up_to_date_when_nothing_stale(monkeypatch):
    result, _ = _run_patch(
        monkeypatch,
        fetch_manifest=lambda: {"phase_3.mf": {"hash": "h", "only": ["linux"]}},
        select_stale=lambda manifest, engine_dir: [],
    )
    assert result["kind"] == "up_to_date"


def test_verify_downloads_and_places_stale(monkeypatch):
    placed = []
    entry = {"dl": "phase_14.mf.f9.bz2", "hash": "x", "compHash": "y"}
    result, _ = _run_patch(
        monkeypatch,
        fetch_manifest=lambda: {"phase_14.mf": entry},
        select_stale=lambda manifest, engine_dir: [("phase_14.mf", entry)],
        resolve_mirror=lambda: "https://m/patches/",
        fetch_verified=lambda e, mirror: b"new",
        place_file=lambda data, dest: placed.append((dest, data)),
    )
    assert result["kind"] == "patched"
    assert result["files"] == ["phase_14.mf"]
    assert placed == [(os.path.join("/engine", "phase_14.mf"), b"new")]


def test_verify_offline_proceeds_as_up_to_date(monkeypatch):
    def boom():
        raise p.requests.RequestException("offline")
    result, _ = _run_patch(monkeypatch, fetch_manifest=boom)
    assert result["kind"] == "up_to_date"


def test_verify_failure_on_download_error(monkeypatch):
    entry = {"dl": "phase_14.mf.bz2", "hash": "x", "compHash": "y"}
    def bad_fetch(e, mirror):
        raise ValueError("hash mismatch")
    result, _ = _run_patch(
        monkeypatch,
        fetch_manifest=lambda: {"phase_14.mf": entry},
        select_stale=lambda manifest, engine_dir: [("phase_14.mf", entry)],
        resolve_mirror=lambda: "https://m/patches/",
        fetch_verified=bad_fetch,
    )
    assert result["kind"] == "failed"
    assert "hash mismatch" in result["msg"]


def test_session_cache_skips_second_verify(monkeypatch):
    manifest = {"phase_3.mf": {"hash": "h", "only": ["linux"]}}
    result1, _ = _run_patch(
        monkeypatch,
        fetch_manifest=lambda: manifest,
        select_stale=lambda m, d: [],
    )
    assert result1["kind"] == "up_to_date"

    # Second run: same manifest; select_stale must NOT be called (cache hit).
    def explode(m, d):
        raise AssertionError("select_stale should be cached")
    monkeypatch.setattr(p, "fetch_manifest", lambda: manifest)
    monkeypatch.setattr(p, "select_stale", explode)
    patcher = p.TTRPatcher()
    done = threading.Event()
    seen = {}
    patcher.up_to_date.connect(lambda: (seen.update(ok=True), done.set()), Qt.DirectConnection)
    patcher.failed.connect(lambda m: (seen.update(fail=m), done.set()), Qt.DirectConnection)
    patcher.verify_and_patch("/engine")
    assert done.wait(2.0)
    assert seen.get("ok") and "fail" not in seen
