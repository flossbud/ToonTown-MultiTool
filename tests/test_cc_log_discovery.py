"""Tests for CC log file discovery layers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from utils import cc_log_discovery

# Snapshot the real implementation so tests can restore it after the
# autouse fixture below stubs it out.
cc_log_discovery_real_candidate_logs_dirs = cc_log_discovery._candidate_logs_dirs


def _fake_proc(open_paths):
    """Build a fake psutil.Process whose open_files() yields the given paths."""
    proc = MagicMock(spec=psutil.Process)
    files = [MagicMock(path=p) for p in open_paths]
    proc.open_files.return_value = files
    proc.create_time.return_value = 0.0
    return proc


@pytest.fixture(autouse=True)
def _isolate_layer2_from_host_filesystem(monkeypatch):
    """The host running these tests may have real CC logs under ~/.wine
    that Layer 2 would discover. Default Layer 2 to a no-op; tests that
    exercise it override the helpers explicitly."""
    monkeypatch.setattr(cc_log_discovery, "_candidate_logs_dirs",
                        lambda pid, manual_dir: [])
    monkeypatch.setattr(cc_log_discovery, "_proc_create_time",
                        lambda pid: 0.0)
    monkeypatch.setattr(cc_log_discovery, "_read_proc_environ",
                        lambda pid: b"")


def test_layer1_returns_cc_log_path_when_psutil_finds_it():
    target = "/home/u/.wine/drive_c/users/u/AppData/Local/Corporate Clash/logs/corporateclash-05-22-2026-11-04-42.log"
    with patch.object(psutil, "Process", return_value=_fake_proc([
        "/usr/lib/wine/wine64",
        target,
        "/tmp/something-unrelated.log",
    ])):
        assert cc_log_discovery.find_log_for_pid(123) == Path(target)


def test_layer1_returns_none_when_no_match():
    with patch.object(psutil, "Process", return_value=_fake_proc([
        "/usr/lib/wine/wine64",
        "/tmp/unrelated.log",
    ])):
        # Layer 2 will not match either because /proc/123/environ is absent
        # and ~/.wine likely lacks the prefix; assert None.
        assert cc_log_discovery.find_log_for_pid(123) is None


def test_layer1_returns_none_on_no_such_process():
    with patch.object(psutil, "Process", side_effect=psutil.NoSuchProcess(123)):
        assert cc_log_discovery.find_log_for_pid(123) is None


def test_layer1_returns_none_on_access_denied():
    proc = MagicMock(spec=psutil.Process)
    proc.open_files.side_effect = psutil.AccessDenied()
    with patch.object(psutil, "Process", return_value=proc):
        assert cc_log_discovery.find_log_for_pid(123) is None


def test_layer2_picks_newest_log_in_logs_dir(tmp_path, monkeypatch):
    """When psutil yields no match, Layer 2 globs each candidate logs dir
    and picks the newest log whose mtime is >= the process create time."""
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "corporateclash-old.log"
    new = logs / "corporateclash-new.log"
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (1_000_500, 1_000_500))
    os.utime(new, (1_001_000, 1_001_000))

    monkeypatch.setattr(cc_log_discovery, "_candidate_logs_dirs",
                        lambda pid, manual_dir: [logs])
    monkeypatch.setattr(cc_log_discovery, "_proc_create_time",
                        lambda pid: 1_000_000)

    with patch.object(psutil, "Process", return_value=_fake_proc([])):
        result = cc_log_discovery.find_log_for_pid(123)
    assert result == new


def test_layer2_skips_log_older_than_process_create_time(tmp_path, monkeypatch):
    """A log file older than the process create time must not be picked."""
    logs = tmp_path / "logs"
    logs.mkdir()
    stale = logs / "corporateclash-old.log"
    stale.write_text("x")
    os.utime(stale, (500, 500))

    monkeypatch.setattr(cc_log_discovery, "_candidate_logs_dirs",
                        lambda pid, manual_dir: [logs])
    monkeypatch.setattr(cc_log_discovery, "_proc_create_time",
                        lambda pid: 1_000_000)

    with patch.object(psutil, "Process", return_value=_fake_proc([])):
        result = cc_log_discovery.find_log_for_pid(123)
    assert result is None


def test_candidate_logs_dirs_uses_wineprefix_from_environ(tmp_path, monkeypatch):
    """_candidate_logs_dirs (unit) reads WINEPREFIX from /proc/$PID/environ
    and returns the resolved AppData logs path under it."""
    wineprefix = tmp_path / "wp"
    logs_dir = (
        wineprefix / "drive_c" / "users" / "u" / "AppData" / "Local"
        / "Corporate Clash" / "logs"
    )
    logs_dir.mkdir(parents=True)

    fake_environ = b"WINEPREFIX=" + str(wineprefix).encode() + b"\x00OTHER=val\x00"
    monkeypatch.setattr(cc_log_discovery, "_read_proc_environ",
                        lambda pid: fake_environ)
    # Restore the real _candidate_logs_dirs (autouse fixture stubbed it).
    monkeypatch.setattr(cc_log_discovery, "_candidate_logs_dirs",
                        cc_log_discovery_real_candidate_logs_dirs)
    # Make sure ~/.wine fallback doesn't pollute the assertion.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")

    dirs = cc_log_discovery._candidate_logs_dirs(123, None)
    assert logs_dir in dirs


def test_candidate_logs_dirs_uses_manual_dir_when_set(tmp_path, monkeypatch):
    """_candidate_logs_dirs returns [manual_dir] when manual_dir is set."""
    manual = tmp_path / "manual_logs"
    manual.mkdir()
    monkeypatch.setattr(cc_log_discovery, "_candidate_logs_dirs",
                        cc_log_discovery_real_candidate_logs_dirs)
    dirs = cc_log_discovery._candidate_logs_dirs(123, manual_dir=manual)
    assert dirs == [manual]


def test_layer3_scans_manual_dir_when_set(tmp_path):
    """When Layer 1 and 2 miss but manual_dir is set, Layer 3 scans it
    and returns the newest .log file regardless of mtime/create-time."""
    manual = tmp_path / "manual_logs"
    manual.mkdir()
    older = manual / "corporateclash-old.log"
    newer = manual / "corporateclash-new.log"
    older.write_text("x")
    newer.write_text("y")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    with patch.object(psutil, "Process", return_value=_fake_proc([])):
        result = cc_log_discovery.find_log_for_pid(123, manual_dir=manual)
    assert result == newer


def test_layer3_does_not_fire_when_manual_dir_is_none():
    """When manual_dir is None, Layer 3 must not run -- no inadvertent scans."""
    with patch.object(psutil, "Process", return_value=_fake_proc([])):
        result = cc_log_discovery.find_log_for_pid(123, manual_dir=None)
    assert result is None


def test_layer1_5_process_scan_finds_cc_when_input_pid_is_wrong(monkeypatch):
    """When the input PID is a sandbox-namespace PID that doesn't map to
    the actual CC process on the host (Faugus / Bottles / Proton case),
    a process-name scan should find the real CC process and return its
    log file."""
    target = "/home/u/Faugus/corporate-clash/drive_c/users/steamuser/AppData/Local/Corporate Clash/logs/corporateclash-05-22-2026-11-43-36.log"

    # Input PID has no matching open files (sandbox-namespace mismatch).
    input_proc = _fake_proc([])
    input_proc.pid = 7914

    # The real CC process on the host has the log file open.
    real_proc = _fake_proc([target])
    real_proc.pid = 52146
    real_proc.info = {"pid": 52146, "name": "CorporateClash.exe"}

    # Unrelated host processes that must be filtered out.
    other = MagicMock(spec=psutil.Process)
    other.info = {"pid": 1, "name": "systemd"}

    def _process_factory(pid):
        if pid == 7914:
            return input_proc
        if pid == 52146:
            return real_proc
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", _process_factory)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [other, real_proc])

    result = cc_log_discovery.find_log_for_pid(7914)
    assert result == Path(target)


def test_layer1_5_skips_processes_with_non_cc_name(monkeypatch):
    """Process-scan only considers CorporateClash-named processes."""
    not_cc = _fake_proc(["/tmp/Corporate Clash/logs/foo.log"])
    not_cc.info = {"pid": 1, "name": "systemd"}

    def _process_factory(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", _process_factory)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [not_cc])

    assert cc_log_discovery.find_log_for_pid(999) is None


class _RaisingProc:
    """Stand-in for a psutil.Process whose .info access raises, simulating
    a process that exited between process_iter() yielding it and our
    later access of its info dict."""

    @property
    def info(self):
        raise psutil.NoSuchProcess(99)


def test_layer1_5_continues_past_transient_process_errors(monkeypatch):
    """A transient psutil.NoSuchProcess on one process in the iter
    must not abort the whole L1.5 scan. The next process named
    CorporateClash.exe should still be discovered."""
    target = "/home/u/.wine/drive_c/users/u/AppData/Local/Corporate Clash/logs/corporateclash-X.log"

    # First proc: accessing .info raises NoSuchProcess.
    bad_proc = _RaisingProc()

    # Second proc: a valid CC process with an open log file.
    good_proc = _fake_proc([target])
    good_proc.info = {"pid": 52146, "name": "CorporateClash.exe"}

    def _process_factory(pid):
        if pid == 52146:
            return good_proc
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", _process_factory)
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs=None: iter([bad_proc, good_proc]))

    result = cc_log_discovery.find_log_for_pid(7914)
    assert result == Path(target)


def test_layer1_respects_manual_dir_scope_filter(tmp_path):
    # manual_dir is interpreted as the "logs" dir itself (shallow glob in
    # Layer 3), so put the in-scope log file directly under tmp_path.
    inside = tmp_path / "corporateclash-05-22-2026.log"
    inside.write_text("x")
    outside_parent = tmp_path.parent / "elsewhere"
    outside_parent.mkdir(exist_ok=True)
    outside = outside_parent / "Corporate Clash" / "logs" / "corporateclash-05-22-2026.log"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("y")

    with patch.object(psutil, "Process", return_value=_fake_proc([str(outside)])):
        # outside is not under tmp_path -> Layer 1 rejects; Layer 2 finds
        # nothing because /proc/123/environ is absent here; Layer 3 then
        # globs tmp_path and finds inside.
        result = cc_log_discovery.find_log_for_pid(123, manual_dir=tmp_path)
        assert result == inside
