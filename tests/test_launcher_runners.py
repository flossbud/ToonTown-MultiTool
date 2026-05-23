"""Launcher runners: open the official TTR / CC launcher without an account.
Tests use monkey-patched subprocess + flatpak detection. No real launches."""
import os
from unittest.mock import MagicMock, patch

from services import launcher_runners


def test_ttr_uses_flatpak_when_available():
    with patch.object(launcher_runners, "_flatpak_installed", return_value=True) as flat, \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_ttr_launcher()
    assert ok is True
    flat.assert_called_once_with("com.toontownrewritten.Launcher")
    args = popen.call_args[0][0]
    assert "flatpak" in args
    assert "com.toontownrewritten.Launcher" in args


def test_ttr_returns_false_when_neither_path_works():
    with patch.object(launcher_runners, "_flatpak_installed", return_value=False), \
         patch.object(launcher_runners, "_xdg_open_desktop_file", return_value=False):
        ok = launcher_runners.run_official_ttr_launcher()
    assert ok is False


def test_cc_returns_false_when_no_installs():
    with patch("services.launcher_runners.discover_cc_installs", return_value=[]):
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is False


def test_cc_single_install_used_directly():
    fake_install = MagicMock()
    fake_install.exe_path = "/fake/CorporateClash.exe"
    with patch("services.launcher_runners.discover_cc_installs", return_value=[fake_install]), \
         patch("services.launcher_runners._cc_launcher_exe_path",
               return_value="/fake/new_launcher.exe"), \
         patch("services.launcher_runners.build_launch_command",
               return_value=(["echo", "ok"], {})) as build, \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is True
    build.assert_called_once()


def test_cc_multiple_installs_uses_stored_signature():
    install_a = MagicMock(); install_a.exe_path = "/a/CorporateClash.exe"
    install_b = MagicMock(); install_b.exe_path = "/b/CorporateClash.exe"
    settings = MagicMock()
    settings.get.return_value = "sig-of-b"
    def sig_side_effect(install):
        return {install_a: "sig-of-a", install_b: "sig-of-b"}[install]
    # Return a launcher path under the picked install's dir so the assertion
    # below ("/b/" in target_exe) still proves we used install_b.
    def resolver_side_effect(install):
        return os.path.join(os.path.dirname(install.exe_path), "new_launcher.exe")
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install_a, install_b]), \
         patch("services.wine_runtimes.install_signature", side_effect=sig_side_effect), \
         patch("services.launcher_runners._cc_launcher_exe_path", side_effect=resolver_side_effect), \
         patch("services.launcher_runners.build_launch_command",
               return_value=(["echo", "ok"], {})) as build, \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_cc_launcher(settings_manager=settings)
    assert ok is True
    # Verify install_b was used (its exe_path is in the target_exe arg)
    call_kwargs = build.call_args.kwargs
    assert "/b/" in call_kwargs["target_exe"]


def test_cc_multiple_installs_no_signature_returns_false():
    install_a = MagicMock(); install_b = MagicMock()
    settings = MagicMock()
    settings.get.return_value = ""  # no stored signature
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install_a, install_b]):
        ok = launcher_runners.run_official_cc_launcher(settings_manager=settings)
    assert ok is False  # caller should prompt picker


def test_cc_stored_signature_no_match_returns_false():
    install_a = MagicMock(); install_b = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "stale-sig-from-deleted-install"
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install_a, install_b]), \
         patch("services.wine_runtimes.install_signature", return_value="some-other-sig"):
        ok = launcher_runners.run_official_cc_launcher(settings_manager=settings)
    assert ok is False


# ── _cc_launcher_exe_path resolution ────────────────────────────────────────


def _make_install(exe_path, prefix_path=None):
    install = MagicMock()
    install.exe_path = exe_path
    install.prefix_path = prefix_path
    return install


def test_cc_launcher_exe_path_finds_new_launcher_in_program_files(tmp_path):
    """Real Faugus layout: launcher in Program Files, game in AppData/Local."""
    prefix = tmp_path / "prefix"
    pf_dir = prefix / "drive_c" / "Program Files" / "Corporate Clash"
    pf_dir.mkdir(parents=True)
    launcher = pf_dir / "new_launcher.exe"
    launcher.write_bytes(b"")
    game_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    game_exe = game_dir / "CorporateClash.exe"
    game_exe.write_bytes(b"")

    install = _make_install(str(game_exe), prefix_path=str(prefix))
    result = launcher_runners._cc_launcher_exe_path(install)
    assert result == str(launcher)


def test_cc_launcher_exe_path_finds_legacy_ttcclauncher(tmp_path):
    """Pre-rename install: legacy TTCCLauncher.exe still resolves."""
    prefix = tmp_path / "prefix"
    pf_dir = prefix / "drive_c" / "Program Files" / "Corporate Clash"
    pf_dir.mkdir(parents=True)
    launcher = pf_dir / "TTCCLauncher.exe"
    launcher.write_bytes(b"")
    game_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    game_exe = game_dir / "CorporateClash.exe"
    game_exe.write_bytes(b"")

    install = _make_install(str(game_exe), prefix_path=str(prefix))
    result = launcher_runners._cc_launcher_exe_path(install)
    assert result == str(launcher)


def test_cc_launcher_exe_path_prefers_new_launcher_over_legacy(tmp_path):
    """When both exist, prefer the modern new_launcher.exe."""
    prefix = tmp_path / "prefix"
    pf_dir = prefix / "drive_c" / "Program Files" / "Corporate Clash"
    pf_dir.mkdir(parents=True)
    (pf_dir / "TTCCLauncher.exe").write_bytes(b"")
    new_launcher = pf_dir / "new_launcher.exe"
    new_launcher.write_bytes(b"")
    game_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    game_exe = game_dir / "CorporateClash.exe"
    game_exe.write_bytes(b"")

    install = _make_install(str(game_exe), prefix_path=str(prefix))
    assert launcher_runners._cc_launcher_exe_path(install) == str(new_launcher)


def test_cc_launcher_exe_path_finds_colocated_with_game(tmp_path):
    """Fallback path: some installs do co-locate launcher next to game."""
    prefix = tmp_path / "prefix"
    game_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    game_exe = game_dir / "CorporateClash.exe"
    game_exe.write_bytes(b"")
    launcher = game_dir / "new_launcher.exe"
    launcher.write_bytes(b"")

    install = _make_install(str(game_exe), prefix_path=str(prefix))
    assert launcher_runners._cc_launcher_exe_path(install) == str(launcher)


def test_cc_launcher_exe_path_returns_none_when_no_binary(tmp_path):
    """Nothing matches anywhere -> None so the caller can fail cleanly."""
    prefix = tmp_path / "prefix"
    game_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    game_exe = game_dir / "CorporateClash.exe"
    game_exe.write_bytes(b"")

    install = _make_install(str(game_exe), prefix_path=str(prefix))
    assert launcher_runners._cc_launcher_exe_path(install) is None


def test_cc_run_returns_false_when_launcher_binary_missing():
    """The end-to-end gate: resolver returns None -> run returns False."""
    install = _make_install("/fake/CorporateClash.exe", prefix_path="/fake/prefix")
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install]), \
         patch("services.launcher_runners._cc_launcher_exe_path", return_value=None), \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is False
    popen.assert_not_called()


def test_cc_run_passes_cwd_as_launcher_directory():
    """The launcher needs cwd set to its own directory; without it, the
    PyInstaller-frozen binary crashes inside Wine (sys.stderr is None
    surfaces, but the underlying issue is resource lookup relative to cwd).
    Faugus's own Play button does this; we must too."""
    install = _make_install("/fake/CorporateClash.exe", prefix_path="/fake/prefix")
    launcher_path = "/fake/prefix/drive_c/Program Files/Corporate Clash/new_launcher.exe"
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install]), \
         patch("services.launcher_runners._cc_launcher_exe_path", return_value=launcher_path), \
         patch("services.launcher_runners.build_launch_command",
               return_value=(["echo", "ok"], {})), \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is True
    assert popen.call_args.kwargs["cwd"] == os.path.dirname(launcher_path)


# ── Steam-Proton resolution cascade ─────────────────────────────────────────


def test_cc_steam_proton_runs_resolver_cascade_before_build(tmp_path):
    """For steam-proton installs the runner must call resolve_effective_proton
    to fill in metadata['proton_dir'] before build_launch_command sees the
    install. Without this, build_launch_command raises ValueError when
    config_info is missing and the runner silently returns False."""
    from services.wine_runtimes import WineInstall

    prefix = tmp_path / "prefix"
    game_dir = prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Corporate Clash"
    game_dir.mkdir(parents=True)
    (game_dir / "CorporateClash.exe").write_bytes(b"")
    pf_dir = prefix / "drive_c" / "Program Files" / "Corporate Clash"
    pf_dir.mkdir(parents=True)
    launcher_exe = pf_dir / "new_launcher.exe"
    launcher_exe.write_bytes(b"")

    install = WineInstall(
        exe_path=str(game_dir / "CorporateClash.exe"),
        launcher="steam-proton",
        prefix_path=str(prefix),
        display_name="Steam · Corporate Clash",
        metadata={
            "appid": "12345",
            "steam_root": str(tmp_path / "steam_root"),
            "proton_dir": None,
        },
    )
    settings = MagicMock()
    settings.get.return_value = ""  # no stored install signature -> single-install path

    seen_install = {}

    def fake_build(install, args, extra_env, target_exe=None):
        seen_install["it"] = install
        return (["fake-cmd"], {})

    with patch("services.launcher_runners.discover_cc_installs", return_value=[install]), \
         patch("services.launcher_runners.resolve_effective_proton",
               return_value="/fake/proton/dir") as resolver, \
         patch("services.launcher_runners.build_launch_command",
               side_effect=fake_build), \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_cc_launcher(settings_manager=settings)

    assert ok is True
    resolver.assert_called_once_with(install, settings)
    patched = seen_install["it"]
    assert patched.metadata["proton_dir"] == "/fake/proton/dir"


def test_cc_steam_proton_returns_false_when_resolver_empty():
    """If resolve_effective_proton returns None (no Proton installed at all),
    the runner must return False instead of letting ValueError surface."""
    from services.wine_runtimes import WineInstall

    install = WineInstall(
        exe_path="/fake/CorporateClash.exe",
        launcher="steam-proton",
        prefix_path="/fake/prefix",
        display_name="Steam · Corporate Clash",
        metadata={"appid": "12345", "steam_root": "/fake/steam", "proton_dir": None},
    )
    settings = MagicMock()
    settings.get.return_value = ""

    with patch("services.launcher_runners.discover_cc_installs", return_value=[install]), \
         patch("services.launcher_runners._cc_launcher_exe_path",
               return_value="/fake/launcher.exe"), \
         patch("services.launcher_runners.resolve_effective_proton",
               return_value=None), \
         patch("services.launcher_runners.build_launch_command") as build, \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        ok = launcher_runners.run_official_cc_launcher(settings_manager=settings)

    assert ok is False
    build.assert_not_called()
    popen.assert_not_called()
