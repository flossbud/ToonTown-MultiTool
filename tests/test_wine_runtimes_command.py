"""Tests for build_launch_command."""

import pytest
from services.wine_runtimes import WineInstall, build_launch_command


def test_native_returns_exe_and_args():
    install = WineInstall(
        exe_path="C:\\Program Files\\Corporate Clash\\CorporateClash.exe",
        launcher="native",
        prefix_path=None,
        display_name="x",
        metadata={},
    )
    cmd, env = build_launch_command(install, ["-g", "srv"], {"CC_OSST_TOKEN": "t"})
    assert cmd == ["C:\\Program Files\\Corporate Clash\\CorporateClash.exe", "-g", "srv"]
    assert env == {"CC_OSST_TOKEN": "t"}


def test_plain_wine_invocation(tmp_path):
    prefix = tmp_path / "prefix"
    exe = prefix / "drive_c/users/me/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="wine",
        prefix_path=str(prefix),
        display_name="x",
        metadata={},
    )
    cmd, env = build_launch_command(install, ["-g", "srv"], {"CC_OSST_TOKEN": "t"})
    assert cmd == ["wine", str(exe), "-g", "srv"]
    assert env["WINEPREFIX"] == str(prefix)
    assert env["CC_OSST_TOKEN"] == "t"


def test_raises_on_unknown_launcher():
    install = WineInstall(
        exe_path="/x",
        launcher="bogus",
        prefix_path=None,
        display_name="x",
        metadata={},
    )
    with pytest.raises(ValueError):
        build_launch_command(install, [], {})
