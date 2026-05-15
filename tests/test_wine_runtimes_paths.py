"""Tests for host_to_windows_path."""

import pytest
from services.wine_runtimes import host_to_windows_path


def test_translates_users_path(tmp_path):
    prefix = tmp_path / "prefix"
    host = prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Corporate Clash" / "CorporateClash.exe"
    host.parent.mkdir(parents=True)
    host.write_text("")
    result = host_to_windows_path(str(host), str(prefix))
    assert result == r"C:\users\steamuser\AppData\Local\Corporate Clash\CorporateClash.exe"


def test_translates_program_files_path(tmp_path):
    prefix = tmp_path / "prefix"
    host = prefix / "drive_c" / "Program Files" / "Corporate Clash" / "CorporateClash.exe"
    host.parent.mkdir(parents=True)
    host.write_text("")
    result = host_to_windows_path(str(host), str(prefix))
    assert result == r"C:\Program Files\Corporate Clash\CorporateClash.exe"


def test_raises_when_path_not_inside_prefix(tmp_path):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    outside = tmp_path / "outside.exe"
    outside.write_text("")
    with pytest.raises(ValueError):
        host_to_windows_path(str(outside), str(prefix))
