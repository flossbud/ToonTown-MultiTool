"""Tests for desktop-file selection in main.py.

The helper picks the appropriate .desktop file id (reverse-DNS or legacy)
based on what's installed on the user's system, with an env override
escape hatch. Cursor-workaround logic was removed; only desktop-file
selection remains testable here.
"""

from unittest.mock import patch

from main import (
    APP_DESKTOP_ID,
    LEGACY_DESKTOP_ID,
    _select_desktop_file_name,
)


def test_selects_reverse_dns_desktop_file_when_installed():
    def fake_isfile(path):
        return path.endswith(f"/applications/{APP_DESKTOP_ID}.desktop")

    with (
        patch("sys.platform", "linux"),
        patch("os.path.isfile", side_effect=fake_isfile),
        patch.dict("os.environ", {"XDG_DATA_DIRS": "/usr/share"}, clear=True),
    ):
        assert _select_desktop_file_name() == APP_DESKTOP_ID


def test_selects_legacy_desktop_file_when_only_legacy_is_installed():
    """If the system has the pre-v2.1.1 AUR install (toontown-multitool.desktop),
    use that id so Qt's setDesktopFileName matches what's on disk."""
    def fake_isfile(path):
        return path.endswith(f"/applications/{LEGACY_DESKTOP_ID}.desktop")

    with (
        patch("sys.platform", "linux"),
        patch("os.path.isfile", side_effect=fake_isfile),
        patch.dict("os.environ", {"XDG_DATA_DIRS": "/usr/share"}, clear=True),
    ):
        assert _select_desktop_file_name() == LEGACY_DESKTOP_ID


def test_desktop_file_name_override_can_disable_explicit_app_id():
    with patch.dict("os.environ", {"TTMT_DESKTOP_FILE_NAME": "none"}, clear=True):
        assert _select_desktop_file_name() is None


def test_desktop_file_name_override_uses_explicit_value():
    with patch.dict(
        "os.environ", {"TTMT_DESKTOP_FILE_NAME": "custom-app-id"}, clear=True
    ):
        assert _select_desktop_file_name() == "custom-app-id"
