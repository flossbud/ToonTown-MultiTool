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


def test_lutris_uses_wine_with_lutris_prefix(tmp_path):
    """Path (b): Lutris-classified installs use plain wine with their stored prefix."""
    prefix = tmp_path / "lutris-prefix"
    exe = prefix / "drive_c/users/lutris/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="lutris",
        prefix_path=str(prefix),
        display_name="x",
        metadata={"lutris_slug": "cc"},
    )
    cmd, env = build_launch_command(install, ["-g", "srv"], {"CC_OSST_TOKEN": "t"})
    assert cmd == ["wine", str(exe), "-g", "srv"]
    assert env["WINEPREFIX"] == str(prefix)


def test_steam_proton_uses_proton_runtime(tmp_path):
    pfx = tmp_path / "compatdata/12345/pfx"
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    proton_dir = tmp_path / "Proton 8.0"
    proton_bin = proton_dir / "proton"
    proton_dir.mkdir()
    proton_bin.write_text("")
    steam_root = tmp_path / "Steam"
    steam_root.mkdir()
    install = WineInstall(
        exe_path=str(exe),
        launcher="steam-proton",
        prefix_path=str(pfx),
        display_name="x",
        metadata={
            "appid": "12345",
            "steam_root": str(steam_root),
            "proton_dir": str(proton_dir),
        },
    )
    cmd, env = build_launch_command(install, ["-g", "srv"], {"CC_OSST_TOKEN": "t"})
    assert cmd == [str(proton_bin), "run", str(exe), "-g", "srv"]
    assert env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "compatdata/12345")
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(steam_root)


def test_steam_proton_raises_when_proton_dir_missing():
    install = WineInstall(
        exe_path="/x.exe",
        launcher="steam-proton",
        prefix_path="/pfx",
        display_name="x",
        metadata={"appid": "1", "steam_root": "/s", "proton_dir": None},
    )
    with pytest.raises(ValueError):
        build_launch_command(install, [], {})


def test_bottles_flatpak_invocation(tmp_path):
    bottle = tmp_path / "Corporate-Clash"
    exe = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="bottles",
        prefix_path=str(bottle),
        display_name="Bottles · CC",
        metadata={
            "bottle_name": "Corporate-Clash",
            "distribution": "flatpak",
        },
    )
    cmd, env = build_launch_command(install, ["-g", "srv"], {"CC_OSST_TOKEN": "t"})
    assert cmd[:4] == [
        "flatpak", "run",
        "--command=bottles-cli", "com.usebottles.bottles",
    ]
    assert "run" in cmd
    assert "-b" in cmd and "Corporate-Clash" in cmd
    # Windows-style path passed via -e
    assert "-e" in cmd
    ei = cmd.index("-e")
    assert cmd[ei + 1].startswith("C:\\")
    # Args are positional trailing tokens (bottles-cli usage:
    # "bottles-cli run [options] [args ...]").
    assert cmd[-2:] == ["-g", "srv"]


def test_bottles_native_invocation(tmp_path):
    bottle = tmp_path / "MyBottle"
    exe = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="bottles",
        prefix_path=str(bottle),
        display_name="x",
        metadata={"bottle_name": "MyBottle", "distribution": "native"},
    )
    cmd, _env = build_launch_command(install, [], {})
    assert cmd[0] == "bottles-cli"
    assert "run" in cmd


def test_bottles_raises_when_prefix_path_missing():
    install = WineInstall(
        exe_path="/x.exe",
        launcher="bottles",
        prefix_path=None,
        display_name="x",
        metadata={"bottle_name": "Some-Bottle", "distribution": "flatpak"},
    )
    with pytest.raises(ValueError):
        build_launch_command(install, [], {})


def test_bottles_raises_when_bottle_name_missing(tmp_path):
    bottle = tmp_path / "Bottle"
    exe = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="bottles",
        prefix_path=str(bottle),
        display_name="x",
        metadata={"distribution": "flatpak"},  # bottle_name missing
    )
    with pytest.raises(ValueError):
        build_launch_command(install, [], {})
