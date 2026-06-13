"""macOS-aware TTR engine discovery: the engine_binary_path resolver and
find_engine_path against the nested .app bundle layout.

Each test PINS sys.platform. A new darwin branch otherwise silently breaks the
Linux/Windows expectations that pass by accident via the non-win32 fallthrough
(see memory project_platform_branch_breaks_unpinned_tests)."""
from __future__ import annotations

import os
import sys

import services.ttr_login_service as tls


def test_engine_binary_path_darwin_nests_in_app_bundle(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    d = "/Users/x/Library/Application Support/Toontown Rewritten"
    assert tls.engine_binary_path(d) == os.path.join(
        d, "Toontown Rewritten.app", "Contents", "MacOS", "TTREngine"
    )


def test_engine_binary_path_linux_is_flat(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    d = "/home/x/Toontown Rewritten"
    assert tls.engine_binary_path(d) == os.path.join(d, "TTREngine")


def test_engine_binary_path_windows_is_flat_exe(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    d = r"C:\Program Files (x86)\Toontown Rewritten"
    assert tls.engine_binary_path(d) == os.path.join(d, "TTREngine64.exe")


def test_find_engine_path_darwin_finds_nested_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "Toontown Rewritten"
    nested = data_dir / "Toontown Rewritten.app" / "Contents" / "MacOS"
    nested.mkdir(parents=True)
    (nested / "TTREngine").write_text("#!/bin/sh\n")
    monkeypatch.setattr(tls, "ENGINE_SEARCH_PATHS", [str(data_dir)])
    assert tls.find_engine_path() == str(data_dir)


def test_find_engine_path_darwin_none_when_bundle_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "Toontown Rewritten"
    data_dir.mkdir()
    # A bare binary in the dir (Linux layout) must NOT satisfy macOS discovery.
    (data_dir / "TTREngine").write_text("#!/bin/sh\n")
    monkeypatch.setattr(tls, "ENGINE_SEARCH_PATHS", [str(data_dir)])
    assert tls.find_engine_path() is None


def test_find_engine_path_linux_finds_flat_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    data_dir = tmp_path / "toontown-rewritten"
    data_dir.mkdir()
    (data_dir / "TTREngine").write_text("#!/bin/sh\n")
    monkeypatch.setattr(tls, "ENGINE_SEARCH_PATHS", [str(data_dir)])
    assert tls.find_engine_path() == str(data_dir)
