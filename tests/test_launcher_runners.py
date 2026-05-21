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


def test_cc_returns_false_when_no_installs():
    with patch("services.launcher_runners.discover_cc_installs", return_value=[]):
        ok = launcher_runners.run_official_cc_launcher()
    assert ok is False


def test_cc_single_install_used_directly():
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


def test_cc_multiple_installs_uses_stored_signature():
    install_a = MagicMock(); install_a.exe_path = "/a/CorporateClash.exe"
    install_b = MagicMock(); install_b.exe_path = "/b/CorporateClash.exe"
    settings = MagicMock()
    settings.get.return_value = "sig-of-b"
    def sig_side_effect(install):
        return {install_a: "sig-of-a", install_b: "sig-of-b"}[install]
    with patch("services.launcher_runners.discover_cc_installs", return_value=[install_a, install_b]), \
         patch("services.wine_runtimes.install_signature", side_effect=sig_side_effect), \
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
