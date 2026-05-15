"""Tests for discover_native_windows."""

import os
from services.wine_runtimes import discover_native_windows, WineInstall


def test_returns_empty_when_no_match(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("os.path.expanduser", lambda p: p.replace("~", str(tmp_path)))
    assert discover_native_windows() == []


def test_finds_install_under_localappdata(tmp_path, monkeypatch):
    install_dir = tmp_path / "LocalAppData" / "Corporate Clash"
    install_dir.mkdir(parents=True)
    (install_dir / "CorporateClash.exe").write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setattr("os.path.expanduser", lambda p: p.replace("~", str(tmp_path)))
    installs = discover_native_windows()
    assert len(installs) == 1
    inst = installs[0]
    assert inst.launcher == "native"
    assert inst.prefix_path is None
    assert inst.exe_path == str(install_dir / "CorporateClash.exe")
    assert "Corporate Clash" in inst.display_name
