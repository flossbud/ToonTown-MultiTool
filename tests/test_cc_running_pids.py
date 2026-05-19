"""Tests for the running-CC PID scanner used by the isolation restart toast."""

from utils import cc_running_pids


def test_scan_returns_empty_when_no_matching_pids(monkeypatch):
    monkeypatch.setattr(cc_running_pids, "_iter_wine_pids", lambda: iter([]))
    assert cc_running_pids.scan_for_prefix("/home/u/.wine") == []


def test_scan_includes_pid_whose_wineprefix_matches(monkeypatch):
    monkeypatch.setattr(
        cc_running_pids, "_iter_wine_pids",
        lambda: iter([12345]),
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_wineprefix_env",
        lambda pid: "/home/u/.wine",
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_cmdline",
        lambda pid: "CorporateClash.exe",
    )

    result = cc_running_pids.scan_for_prefix("/home/u/.wine")
    assert result == [12345]


def test_scan_excludes_pid_with_different_prefix(monkeypatch):
    monkeypatch.setattr(
        cc_running_pids, "_iter_wine_pids",
        lambda: iter([12345]),
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_wineprefix_env",
        lambda pid: "/home/u/.wine-other",
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_cmdline",
        lambda pid: "CorporateClash.exe",
    )

    result = cc_running_pids.scan_for_prefix("/home/u/.wine")
    assert result == []


def test_scan_excludes_non_cc_wine_pid(monkeypatch):
    monkeypatch.setattr(
        cc_running_pids, "_iter_wine_pids",
        lambda: iter([12345]),
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_wineprefix_env",
        lambda pid: "/home/u/.wine",
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_cmdline",
        lambda pid: "notepad.exe",
    )

    result = cc_running_pids.scan_for_prefix("/home/u/.wine")
    assert result == []


def test_scan_normalizes_trailing_slash(monkeypatch):
    monkeypatch.setattr(
        cc_running_pids, "_iter_wine_pids",
        lambda: iter([12345]),
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_wineprefix_env",
        lambda pid: "/home/u/.wine/",
    )
    monkeypatch.setattr(
        cc_running_pids, "_read_cmdline",
        lambda pid: "CorporateClash.exe",
    )

    result = cc_running_pids.scan_for_prefix("/home/u/.wine")
    assert result == [12345]
