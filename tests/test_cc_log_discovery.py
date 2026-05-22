"""Tests for CC log file discovery layers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from utils import cc_log_discovery


def _fake_proc(open_paths):
    """Build a fake psutil.Process whose open_files() yields the given paths."""
    proc = MagicMock(spec=psutil.Process)
    files = [MagicMock(path=p) for p in open_paths]
    proc.open_files.return_value = files
    return proc


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
