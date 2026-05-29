"""Tests for the Corporate Clash game-file patcher."""

import gzip
import hashlib
import os
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


def test_make_object_key_cloudflare_path_scheme():
    # Cloudflare/R2: "<platform>/<filePath-as-posix>.gz"; backslashes -> slashes.
    # (Confirmed live 2026-05-29 by decompiling CC's launcher.util.downloads.)
    assert p.make_object_key("config\\g.prc", "windows", "Cloudflare") == "windows/config/g.prc.gz"
    assert p.make_object_key("resources/default/x.mf", "resources", "Cloudflare") \
        == "resources/resources/default/x.mf.gz"


def test_make_object_key_legacy_sha1_scheme():
    # Any non-Cloudflare server falls back to the legacy sha1(filePath+platform).
    expected = hashlib.sha1(("config\\g.prc" + "windows").encode("utf-8"),
                            usedforsecurity=False).hexdigest()
    assert p.make_object_key("config\\g.prc", "windows", "Legacy Mirror") == expected


def test_fetch_verified_decompresses_and_checks_sha1(monkeypatch):
    raw = b"corporate-clash-file"
    comp = gzip.compress(raw)
    entry = {
        "filePath": "config\\g.prc",
        "sha1": hashlib.sha1(raw, usedforsecurity=False).hexdigest(),
        "_platform": "windows",
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
    assert p.fetch_verified(entry, "https://dl/base", "Cloudflare") == raw
    # URL uses the path-based key, not a hash.
    assert seen["url"] == "https://dl/base/windows/config/g.prc.gz"

    # Wrong decompressed hash -> ValueError. (compressed_sha1 is intentionally
    # NOT checked: CC's gzip framing makes it unstable.)
    with pytest.raises(ValueError):
        p.fetch_verified(dict(entry, sha1="00"), "https://dl/base", "Cloudflare")
    with pytest.raises(ValueError):
        p.fetch_verified({"filePath": "x", "_platform": "windows"}, "https://dl/base", "Cloudflare")


def test_resolve_download_server_reads_realm_nested(monkeypatch):
    # Live CC metadata nests downloadservers INSIDE the matching realm, not at
    # the top level (confirmed 2026-05-29 against production: r2prod R2 host).
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"realms": [
                {"slug": "other", "downloadservers": [{"base_url": "https://dl/other", "name": "X"}]},
                {"slug": "production", "downloadservers": [
                    {"id": 23, "name": "Cloudflare",
                     "base_url": "https://r2prod.corporateclash.net/", "realm": "production"}]},
            ]}
    monkeypatch.setattr(p.requests, "get", lambda url, **k: R())
    assert p.resolve_download_server("tok", "production") == \
        ("https://r2prod.corporateclash.net/", "Cloudflare")


def test_resolve_download_server_raises_without_server(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"realms": [{"slug": "production", "downloadservers": []}]}
    monkeypatch.setattr(p.requests, "get", lambda url, **k: R())
    with pytest.raises(ValueError):
        p.resolve_download_server("tok", "production")


def test_local_path_converts_backslashes(tmp_path):
    assert p._local_path("/game", "config\\g.prc") == os.path.join("/game", "config", "g.prc")


def test_select_stale_direct_detects_mismatch_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: False)
    (tmp_path / "ok.dll").write_bytes(b"hello")
    files = [
        {"filePath": "ok.dll",
         "sha1": hashlib.sha1(b"hello", usedforsecurity=False).hexdigest(),
         "compressed_sha1": "c", "_platform": "windows"},
        {"filePath": "bad.dll", "sha1": "deadbeef", "compressed_sha1": "c", "_platform": "windows"},
        {"filePath": "config\\gone.prc", "sha1": "cafef00d", "compressed_sha1": "c", "_platform": "resources"},
    ]
    stale = {f["filePath"] for f in p.select_stale(files, str(tmp_path))}
    assert stale == {"bad.dll", "config\\gone.prc"}


def test_select_stale_flatpak_uses_host_sha1sum(monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: True)
    files = [
        {"filePath": "ok.dll", "sha1": "aaa", "compressed_sha1": "c", "_platform": "windows"},
        {"filePath": "bad.dll", "sha1": "bbb", "compressed_sha1": "c", "_platform": "windows"},
    ]

    def fake_host_run(argv, **kw):
        ok_path = os.path.join("/game", "ok.dll")
        class _R:
            returncode = 1
            stdout = f"aaa  {ok_path}\n"
        return _R()

    monkeypatch.setattr(p, "host_run", fake_host_run)
    stale = {f["filePath"] for f in p.select_stale(files, "/game")}
    assert stale == {"bad.dll"}


def test_ensure_parent_dir_non_flatpak(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: False)
    dest = tmp_path / "sub" / "deep" / "file.prc"
    p.ensure_parent_dir(str(dest))
    assert (tmp_path / "sub" / "deep").is_dir()


def test_ensure_parent_dir_flatpak_uses_host_mkdir(monkeypatch):
    monkeypatch.setattr(p, "in_flatpak", lambda: True)
    calls = []

    def fake_host_run(argv, **kw):
        calls.append(list(argv))
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(p, "host_run", fake_host_run)
    p.ensure_parent_dir("/game/config/deep/file.prc")
    assert calls == [["mkdir", "-p", "--", "/game/config/deep"]]


def _run_patch(monkeypatch, token="tok", **stubs):
    """Drive CCPatcher.verify_and_patch and return (result, patcher)."""
    _qapp()
    p.reset_verify_cache()
    for name, val in stubs.items():
        monkeypatch.setattr(p, name, val)
    patcher = p.CCPatcher()
    done = threading.Event()
    result = {}
    patcher.up_to_date.connect(lambda: (result.update(kind="up_to_date"), done.set()), Qt.DirectConnection)
    patcher.patched.connect(lambda files: (result.update(kind="patched", files=files), done.set()), Qt.DirectConnection)
    patcher.failed.connect(lambda msg: (result.update(kind="failed", msg=msg), done.set()), Qt.DirectConnection)
    patcher.verify_and_patch("/game", token, "production")
    assert done.wait(2.0), "no terminal signal"
    return result, patcher


def test_verify_up_to_date_when_nothing_stale(monkeypatch):
    result, _ = _run_patch(
        monkeypatch,
        fetch_all_manifests=lambda realm, plat: [{"filePath": "a.dll", "sha1": "h", "_platform": "windows"}],
        select_stale=lambda files, game_dir: [],
    )
    assert result["kind"] == "up_to_date"


def test_verify_downloads_and_places_stale(monkeypatch):
    placed, parents = [], []
    entry = {"filePath": "config\\g.prc", "sha1": "x", "_platform": "windows"}
    result, _ = _run_patch(
        monkeypatch,
        fetch_all_manifests=lambda realm, plat: [entry],
        select_stale=lambda files, game_dir: [entry],
        resolve_download_server=lambda tok, realm: ("https://dl/base", "Cloudflare"),
        fetch_verified=lambda e, base, server_name: b"new",
        ensure_parent_dir=lambda dest: parents.append(dest),
        place_file=lambda data, dest: placed.append((dest, data)),
    )
    assert result["kind"] == "patched"
    assert result["files"] == ["config\\g.prc"]
    assert placed == [(os.path.join("/game", "config", "g.prc"), b"new")]
    assert parents == [os.path.join("/game", "config", "g.prc")]


def test_verify_offline_proceeds_as_up_to_date(monkeypatch):
    def boom(realm, plat):
        raise p.requests.RequestException("offline")
    result, _ = _run_patch(monkeypatch, fetch_all_manifests=boom)
    assert result["kind"] == "up_to_date"


def test_verify_failure_on_download_error(monkeypatch):
    entry = {"filePath": "a.dll", "sha1": "x", "_platform": "windows"}
    def bad_fetch(e, base, server_name):
        raise ValueError("hash mismatch")
    result, _ = _run_patch(
        monkeypatch,
        fetch_all_manifests=lambda realm, plat: [entry],
        select_stale=lambda files, game_dir: [entry],
        resolve_download_server=lambda tok, realm: ("https://dl/base", "Cloudflare"),
        fetch_verified=bad_fetch,
        ensure_parent_dir=lambda dest: None,
    )
    assert result["kind"] == "failed"
    assert "hash mismatch" in result["msg"]


def test_session_cache_skips_second_verify(monkeypatch):
    manifest = [{"filePath": "a.dll", "sha1": "h", "_platform": "windows"}]
    result1, _ = _run_patch(
        monkeypatch,
        fetch_all_manifests=lambda realm, plat: manifest,
        select_stale=lambda files, game_dir: [],
    )
    assert result1["kind"] == "up_to_date"

    def explode(files, game_dir):
        raise AssertionError("select_stale should be cached")
    monkeypatch.setattr(p, "fetch_all_manifests", lambda realm, plat: manifest)
    monkeypatch.setattr(p, "select_stale", explode)
    patcher = p.CCPatcher()
    done = threading.Event()
    seen = {}
    patcher.up_to_date.connect(lambda: (seen.update(ok=True), done.set()), Qt.DirectConnection)
    patcher.failed.connect(lambda m: (seen.update(fail=m), done.set()), Qt.DirectConnection)
    patcher.verify_and_patch("/game", "tok", "production")
    assert done.wait(2.0)
    assert seen.get("ok") and "fail" not in seen
