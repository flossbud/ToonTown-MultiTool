"""Write-side tests for utils/cc_settings.py."""

import json
import os
from pathlib import Path

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


def test_write_is_idempotent_in_outcome(tmp_path):
    """Calling twice yields the same on-disk content and the backup is unchanged."""
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {"jump": "space"}, "want-Custom-Controls": False})

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")
    first = _read(prefs)
    backup_first = _read(prefs.with_suffix(".json.ttmt-backup"))

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")
    second = _read(prefs)
    backup_second = _read(prefs.with_suffix(".json.ttmt-backup"))

    assert first == second
    assert backup_first == backup_second


def test_write_is_atomic_no_tmp_left_on_success(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})

    cc_settings.write_cc_canonical_keymap(prefs, "wasd")

    assert not prefs.with_suffix(".json.ttmt-tmp").exists()


def test_write_propagates_oserror_on_readonly_target(tmp_path):
    prefs = tmp_path / "preferences.json"
    _write(prefs, {"keymap": {}, "want-Custom-Controls": False})
    os.chmod(tmp_path, 0o555)

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


def test_write_canonical_to_all_installs_applies_to_each(tmp_path, monkeypatch):
    prefs_a = tmp_path / "a" / "preferences.json"
    prefs_b = tmp_path / "b" / "preferences.json"
    prefs_a.parent.mkdir()
    prefs_b.parent.mkdir()
    _write(prefs_a, {"keymap": {}, "want-Custom-Controls": False})
    _write(prefs_b, {"keymap": {}, "want-Custom-Controls": False})

    fake_installs = [
        type("I", (), {"prefix_path": str(prefs_a.parent)})(),
        type("I", (), {"prefix_path": str(prefs_b.parent)})(),
    ]

    paths = iter([prefs_a, prefs_b])
    monkeypatch.setattr(cc_settings, "locate_cc_preferences", lambda inst: next(paths))

    results = cc_settings.write_canonical_to_all_installs(fake_installs, "wasd")

    assert all(r.ok for r in results)
    assert _read(prefs_a)["keymap"]["forward"] == "w"
    assert _read(prefs_b)["keymap"]["forward"] == "w"


def test_write_canonical_skips_installs_with_no_prefs(monkeypatch):
    monkeypatch.setattr(cc_settings, "locate_cc_preferences", lambda inst: None)
    fake_installs = [type("I", (), {"prefix_path": "/nope"})()]
    assert cc_settings.write_canonical_to_all_installs(fake_installs, "wasd") == []


def test_restore_all_installs_applies_per_install(tmp_path, monkeypatch):
    prefs_a = tmp_path / "a" / "preferences.json"
    prefs_b = tmp_path / "b" / "preferences.json"
    prefs_a.parent.mkdir()
    prefs_b.parent.mkdir()
    _write(prefs_a.with_suffix(".json.ttmt-backup"), {"marker": "orig-a"})
    _write(prefs_b.with_suffix(".json.ttmt-backup"), {"marker": "orig-b"})
    _write(prefs_a, {"marker": "new-a"})
    _write(prefs_b, {"marker": "new-b"})

    fake_installs = [
        type("I", (), {"prefix_path": str(prefs_a.parent)})(),
        type("I", (), {"prefix_path": str(prefs_b.parent)})(),
    ]
    paths = iter([prefs_a, prefs_b])
    monkeypatch.setattr(cc_settings, "locate_cc_preferences", lambda inst: next(paths))

    results = cc_settings.restore_all_installs(fake_installs)

    assert all(r.ok for r in results)
    assert _read(prefs_a)["marker"] == "orig-a"
    assert _read(prefs_b)["marker"] == "orig-b"
