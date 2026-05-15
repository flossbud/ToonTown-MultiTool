"""Unit tests for ensure_bottle_env_allowlist.

Covers the pure-I/O bottle-YAML mutator that adds env var names to a
bottle's Inherited_Environment_Variables allowlist (which Bottles uses
to filter env vars passed to wine when Limit_System_Environment is on).

These exercise the helper without touching real Bottles state — all
test bottles are constructed in tmp_path with synthetic bottle.yml
files.
"""
from __future__ import annotations

import os

import yaml

from services.wine_runtimes import ensure_bottle_env_allowlist


def _write_bottle(tmp_path, allowlist):
    """Construct a minimal bottle dir with a bottle.yml carrying the
    given Inherited_Environment_Variables list (use None to omit the
    key entirely)."""
    bottle = tmp_path / "TestBottle"
    bottle.mkdir()
    cfg = {"Name": "TestBottle", "Limit_System_Environment": True}
    if allowlist is not None:
        cfg["Inherited_Environment_Variables"] = list(allowlist)
    (bottle / "bottle.yml").write_text(
        yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False)
    )
    return bottle


def _read_allowlist(bottle):
    with open(bottle / "bottle.yml") as f:
        return yaml.safe_load(f).get("Inherited_Environment_Variables") or []


def test_no_bottle_yml_returns_false(tmp_path):
    bottle = tmp_path / "Empty"
    bottle.mkdir()
    assert ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"]) is False


def test_appends_missing_keys_and_writes_backup(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME", "PATH"])
    result = ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE", "TT_GAMESERVER"])
    assert result is True
    assert _read_allowlist(bottle) == ["HOME", "PATH", "TT_PLAYCOOKIE", "TT_GAMESERVER"]
    assert os.path.exists(bottle / "bottle.yml.bak")


def test_appends_only_missing_keys_preserving_order(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME", "TT_PLAYCOOKIE", "PATH"])
    result = ensure_bottle_env_allowlist(
        str(bottle), ["TT_PLAYCOOKIE", "TT_GAMESERVER", "LAUNCHER_USER"]
    )
    assert result is True
    # Pre-existing order preserved; only genuinely-missing keys append at
    # the end, in the order they were requested.
    assert _read_allowlist(bottle) == [
        "HOME", "TT_PLAYCOOKIE", "PATH", "TT_GAMESERVER", "LAUNCHER_USER",
    ]


def test_complete_allowlist_is_noop(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME", "TT_PLAYCOOKIE", "TT_GAMESERVER"])
    result = ensure_bottle_env_allowlist(
        str(bottle), ["TT_PLAYCOOKIE", "TT_GAMESERVER"]
    )
    assert result is False
    # No .bak should be created on a no-op pass.
    assert not os.path.exists(bottle / "bottle.yml.bak")


def test_existing_backup_is_not_overwritten(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME"])
    bak = bottle / "bottle.yml.bak"
    bak.write_text("PRESERVED_BACKUP_CONTENT\n")
    result = ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"])
    assert result is True
    assert bak.read_text() == "PRESERVED_BACKUP_CONTENT\n"


def test_idempotent_across_two_calls(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME"])
    first = ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"])
    second = ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"])
    assert first is True
    assert second is False
    assert _read_allowlist(bottle) == ["HOME", "TT_PLAYCOOKIE"]


def test_allowlist_field_missing_treated_as_empty(tmp_path):
    # A bottle.yml that omits Inherited_Environment_Variables entirely
    # should be treated the same as one with an empty list.
    bottle = _write_bottle(tmp_path, allowlist=None)
    result = ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"])
    assert result is True
    assert _read_allowlist(bottle) == ["TT_PLAYCOOKIE"]


def test_no_temp_file_leaks_after_write(tmp_path):
    bottle = _write_bottle(tmp_path, ["HOME"])
    assert ensure_bottle_env_allowlist(str(bottle), ["TT_PLAYCOOKIE"]) is True
    # The atomic-write tempfile (.ttmt-tmp sibling) must be unlinked
    # by os.replace; if it lingers, the helper isn't atomic.
    assert not (bottle / "bottle.yml.ttmt-tmp").exists()
