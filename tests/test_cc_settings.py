"""Unit tests for CC preferences.json reader."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.cc_settings import (
    locate_cc_preferences, parse_cc_preferences, CcSettings,
)


def _make_steamproton_install(tmp_path, prefs_content):
    """Build a fake Steam-Proton-shaped prefix with preferences.json."""
    prefix = tmp_path / "compatdata" / "12345" / "pfx"
    prefs_dir = prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Corporate Clash"
    prefs_dir.mkdir(parents=True)
    if prefs_content is not None:
        (prefs_dir / "preferences.json").write_text(json.dumps(prefs_content))
    return SimpleNamespace(launcher="steam-proton", prefix_path=str(prefix), exe_path="")


class TestLocateCcPreferences:
    def test_finds_preferences_in_steamproton_prefix(self, tmp_path):
        install = _make_steamproton_install(tmp_path, {"keymap": {}})
        path = locate_cc_preferences(install)
        assert path is not None
        assert path.name == "preferences.json"

    def test_returns_none_when_file_missing(self, tmp_path):
        install = _make_steamproton_install(tmp_path, None)
        assert locate_cc_preferences(install) is None

    def test_finds_under_non_steamuser_wineuser(self, tmp_path):
        """Plain Wine prefixes may use $USER instead of steamuser."""
        prefix = tmp_path / "prefix"
        prefs_dir = prefix / "drive_c" / "users" / "jaret" / "AppData" / "Local" / "Corporate Clash"
        prefs_dir.mkdir(parents=True)
        (prefs_dir / "preferences.json").write_text("{}")
        install = SimpleNamespace(launcher="wine", prefix_path=str(prefix), exe_path="")
        path = locate_cc_preferences(install)
        assert path is not None
        assert "jaret" in str(path)


class TestParseCcPreferences:
    def test_parses_defaults_state(self, tmp_path):
        p = tmp_path / "preferences.json"
        p.write_text(json.dumps({"want-Custom-Controls": False, "keymap": {}}))
        s = parse_cc_preferences(p)
        assert s.want_custom_controls is False
        assert s.keymap == {}
        assert s.source_path == p

    def test_parses_custom_controls(self, tmp_path):
        p = tmp_path / "preferences.json"
        p.write_text(json.dumps({
            "want-Custom-Controls": True,
            "keymap": {"forward": "w", "sprint": "shift"},
        }))
        s = parse_cc_preferences(p)
        assert s.want_custom_controls is True
        assert s.keymap == {"forward": "w", "sprint": "shift"}

    def test_handles_missing_fields(self, tmp_path):
        p = tmp_path / "preferences.json"
        p.write_text("{}")
        s = parse_cc_preferences(p)
        assert s.want_custom_controls is False
        assert s.keymap == {}
