"""Tests for utils.installer_merge — the install-time settings.json merge.

Called via main.py --apply-installer-config from the Inno Setup [Run] section
after files are copied. Always writes check_for_updates_at_startup; only writes
the four Keep-Alive consent keys if keep_alive=True. Preserves all other keys.
Atomic write via temp file + rename. Skips write (with warning return) on
corrupted existing JSON.
"""
import json
import os


def test_creates_file_when_missing(tmp_path):
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=False)
    assert ok is True
    data = json.loads(target.read_text())
    assert data == {"check_for_updates_at_startup": True}


def test_creates_file_with_keep_alive_keys_when_enabled(tmp_path):
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=True)
    assert ok is True
    data = json.loads(target.read_text())
    assert data == {
        "check_for_updates_at_startup": True,
        "keep_alive_enabled": True,
        "keep_alive_consent_acknowledged": True,
        "keep_alive_consent_source": "installer",
        "keep_alive_consent_version": 1,
    }


def test_writes_check_updates_false_when_unchecked(tmp_path):
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    ok = merge_installer_config(str(target), check_updates=False, keep_alive=False)
    assert ok is True
    data = json.loads(target.read_text())
    assert data == {"check_for_updates_at_startup": False}


def test_preserves_existing_keys(tmp_path):
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "theme": "dark",
        "accounts": [{"name": "TestToon"}],
        "custom_keymap": {"jump": "space"},
    }))
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=True)
    assert ok is True
    data = json.loads(target.read_text())
    assert data["theme"] == "dark"
    assert data["accounts"] == [{"name": "TestToon"}]
    assert data["custom_keymap"] == {"jump": "space"}
    assert data["check_for_updates_at_startup"] is True
    assert data["keep_alive_enabled"] is True
    assert data["keep_alive_consent_acknowledged"] is True


def test_replaces_check_updates_on_repeat_install(tmp_path):
    """User re-runs installer and flips the checkbox — value gets overwritten."""
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"check_for_updates_at_startup": True}))
    ok = merge_installer_config(str(target), check_updates=False, keep_alive=False)
    assert ok is True
    data = json.loads(target.read_text())
    assert data["check_for_updates_at_startup"] is False


def test_keep_alive_unchecked_does_not_overwrite_existing_consent(tmp_path):
    """If user previously enabled Keep-Alive in-app, an installer run with
    Keep-Alive unchecked must not strip the consent marker."""
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "keep_alive_enabled": True,
        "keep_alive_consent_acknowledged": True,
    }))
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=False)
    assert ok is True
    data = json.loads(target.read_text())
    assert data["keep_alive_enabled"] is True
    assert data["keep_alive_consent_acknowledged"] is True
    assert data["check_for_updates_at_startup"] is True


def test_skips_corrupted_json(tmp_path):
    """Existing file with invalid JSON: do not mutate, return False."""
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "settings.json"
    target.write_text("{ not valid json")
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=True)
    assert ok is False
    assert target.read_text() == "{ not valid json"


def test_creates_parent_dir_if_missing(tmp_path):
    """If %USERPROFILE%\\.config\\toontown_multitool\\ doesn't exist yet
    (fresh install, app never run), the merge creates it."""
    from utils.installer_merge import merge_installer_config
    target = tmp_path / "nested" / "deeper" / "settings.json"
    ok = merge_installer_config(str(target), check_updates=True, keep_alive=False)
    assert ok is True
    assert target.exists()


def test_atomic_write_uses_temp_file(tmp_path, monkeypatch):
    """The write goes through a .tmp file that is then renamed."""
    from utils import installer_merge
    target = tmp_path / "settings.json"
    seen_paths = []
    orig_replace = os.replace
    def spy_replace(src, dst):
        seen_paths.append((src, dst))
        return orig_replace(src, dst)
    monkeypatch.setattr(os, "replace", spy_replace)
    installer_merge.merge_installer_config(str(target), check_updates=True, keep_alive=False)
    assert len(seen_paths) == 1
    src, dst = seen_paths[0]
    assert src.endswith(".tmp")
    assert dst == str(target)


def test_returns_false_on_write_failure_and_cleans_up_tmp(tmp_path, monkeypatch):
    """If the atomic-replace step raises OSError (e.g. read-only target),
    the function returns False AND the .tmp file is cleaned up so a retry
    is not blocked by a stale partial."""
    from utils import installer_merge
    target = tmp_path / "settings.json"
    def boom(src, dst):
        raise OSError("simulated disk full")
    monkeypatch.setattr(os, "replace", boom)
    ok = installer_merge.merge_installer_config(str(target), check_updates=True, keep_alive=False)
    assert ok is False
    assert not (tmp_path / "settings.json.tmp").exists()
    assert not target.exists()
