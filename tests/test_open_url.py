"""Tests for utils.open_url.

Covers the env-cleaning that fixes the AppImage footer-link bug:
PyInstaller's bootloader sets LD_LIBRARY_PATH to its temp extraction dir,
and any xdg-open child inherits it and crashes against system KF6/Qt6.
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from utils import open_url as open_url_mod


# ── _clean_env ─────────────────────────────────────────────────────────────


def test_clean_env_no_op_when_not_frozen(monkeypatch):
    """In dev (not frozen), env passes through unchanged - the user's
    LD_LIBRARY_PATH (if any) belongs to them, not us."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/user/libs")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    env = open_url_mod._clean_env()
    assert env["LD_LIBRARY_PATH"] == "/user/libs"


def test_clean_env_restores_orig_when_frozen(monkeypatch):
    """When frozen, LD_LIBRARY_PATH is restored from LD_LIBRARY_PATH_ORIG
    (PyInstaller saves the host value there for exactly this case)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxxx")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")

    env = open_url_mod._clean_env()
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env, "internal _ORIG var must not leak to child"


def test_clean_env_drops_var_when_frozen_and_no_orig(monkeypatch):
    """Frozen, no _ORIG sibling -> drop the var so child gets system default."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxxx")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    env = open_url_mod._clean_env()
    assert "LD_LIBRARY_PATH" not in env


def test_clean_env_handles_ld_preload_too(monkeypatch):
    """LD_PRELOAD has the same poisoning risk as LD_LIBRARY_PATH."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_PRELOAD", "/tmp/_MEIxxx/libfoo.so")
    monkeypatch.setenv("LD_PRELOAD_ORIG", "/host/libfoo.so")

    env = open_url_mod._clean_env()
    assert env["LD_PRELOAD"] == "/host/libfoo.so"
    assert "LD_PRELOAD_ORIG" not in env


def test_clean_env_preserves_other_vars(monkeypatch):
    """Only LD_* are touched; everything else (DISPLAY, HOME, ...) is intact."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("LD_PRELOAD", raising=False)

    env = open_url_mod._clean_env()
    assert env["DISPLAY"] == ":0"
    assert env["HOME"] == "/home/user"


# ── open_url dispatch ──────────────────────────────────────────────────────


def test_open_url_returns_false_for_empty_string():
    assert open_url_mod.open_url("") is False
    assert open_url_mod.open_url(None) is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dispatch path")
def test_open_url_linux_uses_xdg_open_with_clean_env(monkeypatch):
    """On Linux outside Flatpak, we Popen xdg-open with a sanitized env."""
    monkeypatch.setattr(open_url_mod, "in_flatpak", lambda: False)
    monkeypatch.setattr(open_url_mod.shutil, "which", lambda _: "/usr/bin/xdg-open")

    fake_popen = MagicMock()
    monkeypatch.setattr(open_url_mod.subprocess, "Popen", fake_popen)

    sentinel_env = {"FAKE": "ENV"}
    monkeypatch.setattr(open_url_mod, "_clean_env", lambda: sentinel_env)

    assert open_url_mod.open_url("https://example.com") is True

    fake_popen.assert_called_once()
    args, kwargs = fake_popen.call_args
    assert args[0] == ["/usr/bin/xdg-open", "https://example.com"]
    assert kwargs["env"] is sentinel_env, "xdg-open must run with cleaned env"
    assert kwargs.get("start_new_session") is True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dispatch path")
def test_open_url_linux_uses_host_popen_under_flatpak(monkeypatch):
    """Inside Flatpak, route through host_popen (which strips LD_* itself)."""
    monkeypatch.setattr(open_url_mod, "in_flatpak", lambda: True)
    fake_host = MagicMock()
    monkeypatch.setattr(open_url_mod, "host_popen", fake_host)

    no_popen = MagicMock(side_effect=AssertionError("must not call subprocess.Popen in Flatpak"))
    monkeypatch.setattr(open_url_mod.subprocess, "Popen", no_popen)

    assert open_url_mod.open_url("https://example.com") is True
    fake_host.assert_called_once_with(["xdg-open", "https://example.com"])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dispatch path")
def test_open_url_linux_falls_back_to_qt_when_popen_oserrors(monkeypatch):
    """If xdg-open spawn fails (OSError), fall back to QDesktopServices."""
    monkeypatch.setattr(open_url_mod, "in_flatpak", lambda: False)
    monkeypatch.setattr(open_url_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        open_url_mod.subprocess, "Popen",
        MagicMock(side_effect=OSError("no xdg-open")),
    )

    with patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=True) as mock_qt:
        assert open_url_mod.open_url("https://example.com") is True
        mock_qt.assert_called_once()


def test_open_url_non_linux_uses_qdesktopservices(monkeypatch):
    """On Windows/macOS, delegate to Qt - there's no LD_* injection issue."""
    monkeypatch.setattr(sys, "platform", "win32")
    with patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=True) as mock_qt:
        assert open_url_mod.open_url("https://example.com") is True
        mock_qt.assert_called_once()
