"""Tests for services.steam_compat_mapping config.vdf parsing."""

import os
import pytest

from services.steam_compat_mapping import steam_compat_choice


VDF_BOTH_KEYS = '''
"InstallConfigStore"
{
  "Software"
  {
    "Valve"
    {
      "Steam"
      {
        "CompatToolMapping"
        {
          "0"
          {
            "name"     "proton_experimental"
            "config"   ""
            "priority" "250"
          }
          "1234567890"
          {
            "name"     "proton-cachyos"
            "config"   ""
            "priority" "250"
          }
        }
      }
    }
  }
}
'''


def _write_config(tmp_path, contents):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    cfg = cfg_dir / "config.vdf"
    cfg.write_text(contents)
    return str(tmp_path)


def test_returns_per_appid_value(tmp_path):
    root = _write_config(tmp_path, VDF_BOTH_KEYS)
    assert steam_compat_choice(root, "1234567890") == "proton-cachyos"


VDF_GLOBAL_ONLY = '''
"InstallConfigStore"
{
  "Software"
  {
    "Valve"
    {
      "Steam"
      {
        "CompatToolMapping"
        {
          "0"
          {
            "name"     "proton_9"
            "priority" "250"
          }
        }
      }
    }
  }
}
'''


VDF_EMPTY_NAMES = '''
"InstallConfigStore"
{
  "Software"
  {
    "Valve"
    {
      "Steam"
      {
        "CompatToolMapping"
        {
          "0"
          {
            "name"     ""
          }
          "9999"
          {
            "name"     ""
          }
        }
      }
    }
  }
}
'''


VDF_MISSING_MAPPING = '''
"InstallConfigStore"
{
  "Software"
  {
    "Valve"
    {
      "Steam"
      {
      }
    }
  }
}
'''


def test_falls_back_to_global_default(tmp_path):
    root = _write_config(tmp_path, VDF_GLOBAL_ONLY)
    assert steam_compat_choice(root, "1234567890") == "proton_9"


def test_per_appid_takes_precedence_over_global(tmp_path):
    root = _write_config(tmp_path, VDF_BOTH_KEYS)
    # 1234567890 is set per-appid; should NOT return global.
    assert steam_compat_choice(root, "1234567890") == "proton-cachyos"


def test_empty_names_return_none(tmp_path):
    root = _write_config(tmp_path, VDF_EMPTY_NAMES)
    assert steam_compat_choice(root, "9999") is None


def test_missing_mapping_block_returns_none(tmp_path):
    root = _write_config(tmp_path, VDF_MISSING_MAPPING)
    assert steam_compat_choice(root, "9999") is None


def test_missing_file_returns_none(tmp_path):
    assert steam_compat_choice(str(tmp_path), "9999") is None


def test_truncated_file_returns_none(tmp_path):
    root = _write_config(tmp_path, '"InstallConfigStore"\n{\n  "Software"\n  {')
    # Mid-block truncation — walk_to_mapping should fail cleanly.
    assert steam_compat_choice(root, "9999") is None


def test_unrelated_appid_falls_back_to_global(tmp_path):
    root = _write_config(tmp_path, VDF_BOTH_KEYS)
    # 9999 isn't in the file → return global default ("proton_experimental").
    assert steam_compat_choice(root, "9999") == "proton_experimental"
