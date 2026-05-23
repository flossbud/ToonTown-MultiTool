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
    cmd, env = build_launch_command(install, ["-g", "srv"], {"TT_PLAYCOOKIE": "t"})
    assert cmd == ["C:\\Program Files\\Corporate Clash\\CorporateClash.exe", "-g", "srv"]
    assert env == {"TT_PLAYCOOKIE": "t"}


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
    cmd, env = build_launch_command(install, ["-g", "srv"], {"TT_PLAYCOOKIE": "t"})
    assert cmd == ["wine", str(exe), "-g", "srv"]
    assert env["WINEPREFIX"] == str(prefix)
    assert env["TT_PLAYCOOKIE"] == "t"


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
    cmd, env = build_launch_command(install, ["-g", "srv"], {"TT_PLAYCOOKIE": "t"})
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
    cmd, env = build_launch_command(install, ["-g", "srv"], {"TT_PLAYCOOKIE": "t"})
    assert cmd == [str(proton_bin), "waitforexitandrun", str(exe), "-g", "srv"]
    assert env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "compatdata/12345")
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(steam_root)


def test_steam_proton_wraps_in_slr_when_required(tmp_path):
    """When proton toolmanifest.vdf declares require_tool_appid AND the
    referenced SteamLinuxRuntime is installed, the command is wrapped
    in <slr>/_v2-entry-point. Without that wrapper, modern Protons
    built against the SLR's libc fail with no Wine output (the symptom
    that motivated this code path)."""
    import os
    pfx = tmp_path / "compatdata/12345/pfx"
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    # Proton that declares it needs SLR appid 4183110.
    proton_dir = tmp_path / "Steam/compatibilitytools.d/proton-cachyos"
    proton_dir.mkdir(parents=True)
    proton_bin = proton_dir / "proton"
    proton_bin.write_text("")
    (proton_dir / "toolmanifest.vdf").write_text(
        '"manifest"\n{\n'
        '  "version" "2"\n'
        '  "commandline" "/proton %verb%"\n'
        '  "require_tool_appid" "4183110"\n'
        "}\n"
    )
    steam_root = tmp_path / "Steam"
    # Steam appmanifest pointing at the runtime install dir.
    apps = steam_root / "steamapps"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "appmanifest_4183110.acf").write_text(
        '"AppState"\n{\n'
        '  "appid" "4183110"\n'
        '  "name" "Steam Linux Runtime 4.0"\n'
        '  "installdir" "SteamLinuxRuntime_4"\n'
        "}\n"
    )
    # The actual entry point script — needs to exist + be executable.
    slr_dir = apps / "common" / "SteamLinuxRuntime_4"
    slr_dir.mkdir(parents=True)
    entry = slr_dir / "_v2-entry-point"
    entry.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(entry, 0o755)

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
    cmd, env = build_launch_command(install, [], {"TT_PLAYCOOKIE": "t"})
    assert cmd == [
        str(entry), "--verb=waitforexitandrun", "--",
        str(proton_bin), "waitforexitandrun", str(exe),
    ]
    assert env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "compatdata/12345")
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(steam_root)


def test_steam_proton_falls_back_to_direct_when_slr_missing(tmp_path):
    """If require_tool_appid is set but the appmanifest isn't installed,
    fall back to direct proton invocation. Better to attempt the launch
    than to refuse to run."""
    pfx = tmp_path / "compatdata/12345/pfx"
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    proton_dir = tmp_path / "Proton"
    proton_dir.mkdir()
    proton_bin = proton_dir / "proton"
    proton_bin.write_text("")
    (proton_dir / "toolmanifest.vdf").write_text(
        '"manifest" { "require_tool_appid" "9999999" }\n'
    )
    steam_root = tmp_path / "Steam"
    steam_root.mkdir()
    # NOTE: no appmanifest_9999999.acf — runtime not installed.

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
    cmd, _env = build_launch_command(install, [], {})
    assert cmd == [str(proton_bin), "waitforexitandrun", str(exe)]


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
    cmd, env = build_launch_command(install, ["-g", "srv"], {"TT_PLAYCOOKIE": "t"})
    assert cmd[:4] == [
        "flatpak", "run",
        "--command=bottles-cli", "com.usebottles.bottles",
    ]
    assert "run" in cmd
    assert "-b" in cmd
    # bottles-cli identifies bottles by display name (from bottle.yml), but
    # falls back to bottle_name when display name is missing. This test
    # passes only bottle_name, so the dir-basename fallback is used.
    assert "Corporate-Clash" in cmd
    # Unix exec path passed via -e (sidesteps bottles'
    # WineExecutor.__get_cwd quoting bug on Windows paths).
    assert "-e" in cmd
    ei = cmd.index("-e")
    assert cmd[ei + 1] == str(exe)
    # POSIX '--' terminator separates bottles-cli's own flags from the
    # trailing tokens that get forwarded to the executable.
    assert "--" in cmd
    dashdash = cmd.index("--")
    assert cmd[dashdash + 1:] == ["-g", "srv"]


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


def test_bottles_missing_distribution_falls_back_to_native_when_cli_present(
    tmp_path, monkeypatch,
):
    """If metadata lacks 'distribution' (e.g., a WineInstall built by
    classify_path before the distribution-detection fix shipped, or a
    future caller that constructs WineInstall by hand), build must probe
    bottles-cli on PATH and prefer the native form. Otherwise users with
    only the RPM/AUR Bottles get a flatpak run that errors with
    'app/com.usebottles.bottles not installed'."""
    import services.wine_runtimes as wr
    bottle = tmp_path / "MyBottle"
    exe = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="bottles",
        prefix_path=str(bottle),
        display_name="x",
        metadata={"bottle_name": "MyBottle"},  # no 'distribution'
    )
    monkeypatch.setattr(wr, "_host_command_exists",
                        lambda name: name == "bottles-cli")
    cmd, _env = build_launch_command(install, [], {})
    assert cmd[0] == "bottles-cli"
    assert "flatpak" not in cmd


def test_bottles_missing_distribution_falls_back_to_flatpak_when_no_cli(
    tmp_path, monkeypatch,
):
    """Inverse of the above: when 'distribution' is unset and bottles-cli
    is NOT on PATH, fall back to the flatpak form. Only flatpak Bottles
    installed → flatpak invocation."""
    import services.wine_runtimes as wr
    bottle = tmp_path / "MyBottle"
    exe = bottle / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe),
        launcher="bottles",
        prefix_path=str(bottle),
        display_name="x",
        metadata={"bottle_name": "MyBottle"},  # no 'distribution'
    )
    monkeypatch.setattr(wr, "_host_command_exists", lambda name: False)
    cmd, _env = build_launch_command(install, [], {})
    assert cmd[0] == "flatpak"
    assert "com.usebottles.bottles" in cmd


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


def test_faugus_flatpak_emits_message_string_for_runner_py():
    """faugus-run's CLI is `[--game GAME] [message] [command]`, not -e/-p/-r.
    The message is a shell-style string from which Faugus's runner.py
    extract_env_from_message() pulls KEY=VAL tokens into os.environ and
    Popens the remainder. This mirrors faugus.runner.build_launch_command(game).
    Regression for the launch error 'unrecognized arguments: -e -p -r'."""
    from services.wine_runtimes import WineInstall, build_launch_command
    install = WineInstall(
        exe_path="/home/u/Faugus/corporate-clash/drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/home/u/Faugus/corporate-clash",
        display_name="Faugus · Corporate Clash",
        metadata={
            "faugus_runner": "Proton-CachyOS Latest",
            "faugus_install_kind": "flatpak",
            "faugus_gameid": "corporate-clash",
        },
    )
    cmd, env = build_launch_command(install, [], {"TT_PLAYCOOKIE": "t", "REALM": "production"})
    # cmd is [flatpak, run, --command=faugus-run, <app-id>, <message>] — exactly 5 items.
    assert cmd[:4] == [
        "flatpak", "run", "--command=faugus-run",
        "io.github.Faugus.faugus-launcher",
    ]
    assert len(cmd) == 5, f"expected exactly one message arg, got {cmd}"
    msg = cmd[4]
    # No -e/-p/-r flags — those crash runner.py.
    assert " -e " not in f" {msg} "
    assert " -p " not in f" {msg} "
    assert " -r " not in f" {msg} "
    # Env-prefix tokens that runner.py will lift into os.environ.
    assert "LOG_DIR=corporate-clash" in msg
    assert "GAMEID=corporate-clash" in msg
    assert "WINEPREFIX=/home/u/Faugus/corporate-clash" in msg
    assert "PROTONPATH='Proton-CachyOS Latest'" in msg
    # umu-run path inside the Flatpak user-data tree (same path on host and sandbox).
    assert "/.var/app/io.github.Faugus.faugus-launcher/data/faugus-launcher/umu-run" in msg
    # The target exe (quoted because it contains spaces).
    assert (
        "'/home/u/Faugus/corporate-clash/drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe'"
        in msg
    )
    assert env == {"TT_PLAYCOOKIE": "t", "REALM": "production"}


def test_faugus_native_uses_bare_faugus_run_with_message():
    from services.wine_runtimes import WineInstall, build_launch_command
    install = WineInstall(
        exe_path="/x/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/p",
        display_name="Faugus · CC",
        metadata={
            "faugus_runner": "GE-Proton9-1",
            "faugus_install_kind": "native",
            "faugus_gameid": "corporate-clash",
        },
    )
    cmd, env = build_launch_command(install, [], {"TT_PLAYCOOKIE": "t"})
    assert cmd[0] == "faugus-run"
    assert len(cmd) == 2, f"expected exactly one message arg, got {cmd}"
    msg = cmd[1]
    assert "GAMEID=corporate-clash" in msg
    assert "WINEPREFIX=/p" in msg
    assert "PROTONPATH=GE-Proton9-1" in msg
    assert "/.local/share/faugus-launcher/umu-run" in msg
    assert "/x/CorporateClash.exe" in msg


def test_faugus_omits_protonpath_when_runner_empty():
    """Scan-fallback installs have no captured runner; omit PROTONPATH so
    umu-launcher falls through to its default."""
    from services.wine_runtimes import WineInstall, build_launch_command
    install = WineInstall(
        exe_path="/x/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/p",
        display_name="Faugus · CC",
        metadata={"faugus_runner": "", "faugus_install_kind": "scan"},
    )
    cmd, env = build_launch_command(install, [], {})
    assert cmd[0] == "faugus-run"
    msg = cmd[1]
    assert "PROTONPATH" not in msg
    assert "WINEPREFIX=/p" in msg


def test_faugus_appends_game_args_to_message():
    """Args passed to build_launch_command are CLI args for the .exe and must
    land after the exe path inside the message, not as flags to faugus-run."""
    from services.wine_runtimes import WineInstall, build_launch_command
    install = WineInstall(
        exe_path="/x/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/p",
        display_name="Faugus · CC",
        metadata={"faugus_install_kind": "native", "faugus_gameid": "cc"},
    )
    cmd, _env = build_launch_command(install, ["-g", "newgame", "--realm", "prod"], {})
    msg = cmd[1]
    # exe must come before the game args.
    exe_pos = msg.index("/x/CorporateClash.exe")
    arg_pos = msg.index("-g")
    assert exe_pos < arg_pos
    assert "newgame" in msg
    assert "--realm" in msg
    assert "prod" in msg


def test_faugus_requires_prefix_path():
    from services.wine_runtimes import WineInstall, build_launch_command
    install = WineInstall(
        exe_path="/x/CorporateClash.exe",
        launcher="faugus",
        prefix_path=None,
        display_name="Faugus · CC",
        metadata={"faugus_runner": "Proton"},
    )
    with pytest.raises(ValueError):
        build_launch_command(install, [], {})
