"""Tests for the startup CC prefs auto-lock in main._lock_cc_prefs_silently."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import main


def _read(path):
    return json.loads(Path(path).read_text())


def _write(path, data):
    Path(path).write_text(json.dumps(data, indent=4))


def test_lock_skipped_when_no_installs(monkeypatch, capsys):
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs", lambda: [])
    main._lock_cc_prefs_silently()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_lock_writes_canonical_to_every_install(monkeypatch, tmp_path):
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
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs", lambda: fake_installs)

    paths = iter([prefs_a, prefs_b])
    from utils import cc_settings
    monkeypatch.setattr(cc_settings, "locate_cc_preferences", lambda inst: next(paths))

    main._lock_cc_prefs_silently()

    assert _read(prefs_a)["keymap"]["forward"] == "w"
    assert _read(prefs_a)["want-Custom-Controls"] is True
    assert _read(prefs_b)["keymap"]["forward"] == "w"


def test_lock_swallows_discover_exception(monkeypatch, capsys):
    def boom():
        raise RuntimeError("disk unmounted")
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs", boom)

    main._lock_cc_prefs_silently()  # must not raise

    err = capsys.readouterr().out + capsys.readouterr().err
    # The error path prints to stdout; we don't assert exact wording.


def test_lock_reports_partial_write_failure(monkeypatch, tmp_path, capsys):
    """If one install's write fails, the others still get written and the
    failure is logged but doesn't raise."""
    prefs_ok = tmp_path / "ok" / "preferences.json"
    prefs_bad = tmp_path / "bad" / "preferences.json"
    prefs_ok.parent.mkdir()
    prefs_bad.parent.mkdir()
    _write(prefs_ok, {"keymap": {}, "want-Custom-Controls": False})
    _write(prefs_bad, {"keymap": {}, "want-Custom-Controls": False})

    fake_installs = [
        type("I", (), {"prefix_path": str(prefs_ok.parent)})(),
        type("I", (), {"prefix_path": str(prefs_bad.parent)})(),
    ]
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs", lambda: fake_installs)

    from utils import cc_settings
    paths = iter([prefs_ok, prefs_bad])
    monkeypatch.setattr(cc_settings, "locate_cc_preferences", lambda inst: next(paths))

    # Inject one failure: monkeypatch write_cc_canonical_keymap to fail on the second path.
    real_write = cc_settings.write_cc_canonical_keymap
    def selective_write(path, canonical):
        if "bad" in str(path):
            return cc_settings.WriteResult(ok=False, error="permission denied")
        return real_write(path, canonical)
    monkeypatch.setattr(cc_settings, "write_cc_canonical_keymap", selective_write)

    main._lock_cc_prefs_silently()  # must not raise

    assert _read(prefs_ok)["keymap"]["forward"] == "w"
    captured = capsys.readouterr()
    assert "partial failure" in captured.out
