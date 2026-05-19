"""Write-side tests for utils/cc_settings.py."""

import json
import os
from pathlib import Path

import pytest

from utils import cc_settings


def _read(path):
    return json.loads(Path(path).read_text())


def _write(path, data):
    Path(path).write_text(json.dumps(data, indent=4))


def test_write_wasd_canonical_produces_expected_keymap(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})

    result = cc_settings.write_cc_canonical_keymap(prefs, "wasd")
    assert result.ok

    data = _read(prefs)
    assert data["want-Custom-Controls"] is True
    assert data["keymap"]["forward"] == "w"
    assert data["keymap"]["reverse"] == "s"
    assert data["keymap"]["left"] == "a"
    assert data["keymap"]["right"] == "d"


def test_write_arrows_canonical_produces_expected_keymap(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})

    result = cc_settings.write_cc_canonical_keymap(prefs, "arrows")
    assert result.ok

    data = _read(prefs)
    assert data["keymap"]["forward"] == "arrow_up"
    assert data["keymap"]["reverse"] == "arrow_down"
    assert data["keymap"]["left"] == "arrow_left"
    assert data["keymap"]["right"] == "arrow_right"


def test_write_preserves_non_movement_bindings(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {
        "keymap": {"jump": "space", "gags": "q", "tasks": "e", "book": "escape"},
        "want-Custom-Controls": True,
    })

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    km = _read(prefs)["keymap"]
    assert km["jump"] == "space"
    assert km["gags"] == "q"
    assert km["tasks"] == "e"
    assert km["book"] == "escape"


def test_write_preserves_unknown_top_level_keys(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {
        "keymap": {},
        "want-Custom-Controls": False,
        "musicVol": 0.42,
        "exoticSetting": "preserved",
    })

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    data = _read(prefs)
    assert data["musicVol"] == 0.42
    assert data["exoticSetting"] == "preserved"


def test_write_creates_backup_on_first_call(tmp_path):
    prefs = tmp_path / "preferences.json"
    original = {"keymap": {}, "want-Custom-Controls": False, "marker": "v1"}
    _write(prefs, original)

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    backup = prefs.with_suffix(".json.ttmt-backup")
    assert backup.exists()
    assert _read(backup) == original


def test_write_does_not_overwrite_existing_backup(tmp_path):
    prefs = tmp_path / "preferences.json"
    backup = prefs.with_suffix(".json.ttmt-backup")
    _write(prefs, {"keymap": {}, "marker": "later-edit"})
    _write(backup, {"keymap": {}, "marker": "true-original"})

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    assert _read(backup)["marker"] == "true-original"


def test_write_creates_stub_when_prefs_missing(tmp_path):
    prefs = tmp_path / "preferences.json"
    assert not prefs.exists()

    result = cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    assert result.ok
    data = _read(prefs)
    assert data["want-Custom-Controls"] is True
    assert data["keymap"]["forward"] == "w"


def test_write_is_atomic_no_tmp_left_on_success(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    tmp_path_residue = prefs.with_suffix(".json.ttmt-tmp")
    assert not tmp_path_residue.exists()


def test_write_propagates_oserror_on_readonly_target(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})
    os.chmod(tmp_path, 0o555)  # read-only dir

    try:
        result = cc_settings.write_cc_canonical_keymap(prefs, "wasd")
        assert not result.ok
        assert result.error is not None
    finally:
        os.chmod(tmp_path, 0o755)


def test_restore_copies_backup_back_and_removes_it(tmp_path):
    prefs = tmp_path / "preferences.json"
    backup = prefs.with_suffix(".json.ttmt-backup")
    _write(backup, {"marker": "original"})
    _write(prefs, {"marker": "rewritten"})

    result = cc_settings.restore_cc_prefs(prefs)

    assert result.ok
    assert _read(prefs)["marker"] == "original"
    assert not backup.exists()


def test_restore_returns_error_when_no_backup(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"marker": "rewritten"})

    result = cc_settings.restore_cc_prefs(prefs)

    assert not result.ok
    assert "backup" in (result.error or "").lower()


def test_detect_custom_bindings_empty(tmp_path):
    settings = cc_settings.CcSettings(keymap={}, want_custom_controls=False)
    assert cc_settings.detect_custom_bindings(settings) == "empty"


def test_detect_custom_bindings_stock_wasd(tmp_path):
    settings = cc_settings.CcSettings(
        keymap={"forward": "w", "reverse": "s", "left": "a", "right": "d"},
        want_custom_controls=True,
    )
    assert cc_settings.detect_custom_bindings(settings) == "stock_wasd_or_arrows"


def test_detect_custom_bindings_stock_arrows(tmp_path):
    settings = cc_settings.CcSettings(
        keymap={
            "forward": "arrow_up", "reverse": "arrow_down",
            "left": "arrow_left", "right": "arrow_right",
        },
        want_custom_controls=True,
    )
    assert cc_settings.detect_custom_bindings(settings) == "stock_wasd_or_arrows"


def test_detect_custom_bindings_user_custom(tmp_path):
    settings = cc_settings.CcSettings(
        keymap={"forward": "i", "reverse": "k", "left": "j", "right": "l"},
        want_custom_controls=True,
    )
    assert cc_settings.detect_custom_bindings(settings) == "user_custom"
