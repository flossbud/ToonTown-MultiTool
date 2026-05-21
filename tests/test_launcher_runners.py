"""Launcher runners: open the official TTR / CC launcher without an account.
Tests use monkey-patched subprocess + flatpak detection. No real launches."""
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


def test_cc_uses_existing_wine_path():
    fake_install = MagicMock()
    fake_install.exe_path = "/fake/CorporateClash.exe"
    with patch("services.launcher_runners.discover_cc_installs", return_value=[fake_install]), \
         patch("services.launcher_runners.build_launch_command",
               return_value=(["echo", "ok"], {})) as build, \
         patch.object(launcher_runners.subprocess, "Popen") as popen:
        popen.return_value = MagicMock()
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is True
    build.assert_called_once()
    # build_launch_command should have been called with target_exe pointing at TTCCLauncher.exe
    call_kwargs = build.call_args.kwargs
    assert "target_exe" in call_kwargs
    assert call_kwargs["target_exe"].endswith("TTCCLauncher.exe")
    popen.assert_called_once()


def test_cc_returns_false_when_no_installs():
    with patch("services.launcher_runners.discover_cc_installs", return_value=[]):
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is False
