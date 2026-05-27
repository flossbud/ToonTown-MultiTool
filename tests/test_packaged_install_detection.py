"""Tests for `_is_packaged_install` and the dev-vs-packaged gating in
`_select_desktop_file_name`.

The motivating bug: a user can have a packaged install (e.g. Flatpak) of TTMT
alongside a from-source dev clone. The Flatpak exports its `.desktop` and icon
into system XDG paths visible to the dev run. Without gating, the dev run
borrows the Flatpak's `.desktop` as its Wayland app_id, causing the WM to
render the Flatpak's (potentially stale) icon in the taskbar."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _clear_packaging_env(monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("TTMT_DESKTOP_FILE_NAME", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)


def test_is_packaged_install_false_for_dev_clone_under_home(monkeypatch):
    """A dev clone under $HOME with no packaging env vars is NOT packaged."""
    import main
    _clear_packaging_env(monkeypatch)
    # main.__file__ lives under $HOME in the dev repo. Just sanity-check.
    home = os.path.expanduser("~")
    script_dir = os.path.dirname(os.path.abspath(main.__file__))
    assert script_dir.startswith(home + os.sep), (
        f"test precondition: main.py should be under $HOME for this test "
        f"({script_dir} vs {home})"
    )
    assert main._is_packaged_install() is False


def test_is_packaged_install_true_when_frozen(monkeypatch):
    """PyInstaller-built binaries (Windows EXE, AppImage with PyInstaller)
    set `sys.frozen = True`."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert main._is_packaged_install() is True


def test_is_packaged_install_true_when_appimage_env_set(monkeypatch):
    """AppImage's runtime sets the `APPIMAGE` env var even when not frozen."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setenv("APPIMAGE", "/tmp/ToonTownMultiTool.AppImage")
    assert main._is_packaged_install() is True


def test_is_packaged_install_true_when_flatpak_id_is_ours(monkeypatch):
    """Running inside our own Flatpak sandbox: FLATPAK_ID matches our app id."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setenv("FLATPAK_ID", main.APP_DESKTOP_ID)
    assert main._is_packaged_install() is True


def test_is_packaged_install_true_when_flatpak_id_is_beta(monkeypatch):
    """Same as above for the beta channel."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setenv("FLATPAK_ID", main.BETA_DESKTOP_ID)
    assert main._is_packaged_install() is True


def test_select_desktop_file_name_ignores_system_desktop_in_dev(monkeypatch):
    """Dev runs must not borrow a system-installed `.desktop` entry that may
    belong to a different (previously installed) version of ourselves. Even if
    `_desktop_file_exists` returns True, return None so Qt does not set the
    Wayland app_id from a foreign install."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setattr(main, "_is_packaged_install", lambda: False, raising=False)
    monkeypatch.setattr(main, "_desktop_file_exists", lambda _id: True)
    assert main._select_desktop_file_name() is None


def test_select_desktop_file_name_trusts_system_desktop_when_packaged(monkeypatch):
    """Packaged installs (AUR/.deb/RPM/Flatpak/AppImage) own their `.desktop`
    file, so the existing precedence is preserved when packaged."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setattr(main, "_is_packaged_install", lambda: True, raising=False)
    monkeypatch.setattr(
        main, "_desktop_file_exists", lambda did: did == main.APP_DESKTOP_ID
    )
    assert main._select_desktop_file_name() == main.APP_DESKTOP_ID


def test_select_desktop_file_name_skips_appimage_host_desktop_ids(monkeypatch):
    """AppImages should use the per-window icon unless explicitly overridden.

    Host XDG desktop files may belong to a stale Flatpak/AUR install of the
    same app id, which makes KDE Wayland bind the AppImage window to the wrong
    taskbar icon.
    """
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setenv("APPIMAGE", "/tmp/TTMultiTool.AppImage")
    monkeypatch.setattr(main, "_desktop_file_exists", lambda _id: True)
    assert main._select_desktop_file_name() is None


def test_select_desktop_file_name_honours_explicit_override(monkeypatch):
    """`TTMT_DESKTOP_FILE_NAME` env override wins over any gating, both for
    explicit values and the disable sentinels."""
    import main
    _clear_packaging_env(monkeypatch)
    monkeypatch.setattr(main, "_is_packaged_install", lambda: False, raising=False)
    monkeypatch.setattr(main, "_desktop_file_exists", lambda _id: True)
    monkeypatch.setenv("TTMT_DESKTOP_FILE_NAME", "custom.id")
    assert main._select_desktop_file_name() == "custom.id"
    monkeypatch.setenv("TTMT_DESKTOP_FILE_NAME", "off")
    assert main._select_desktop_file_name() is None
