"""Tests for utils.ttr_settings — the TTR settings.json reader and chat-rule resolver."""
import json
import os
from pathlib import Path

import pytest

from utils.ttr_settings import (
    TtrSettings,
    parse_ttr_settings,
    resolve_chat_block_list,
)


def _write_settings(tmp_path: Path, controls: dict, extras: dict = None) -> Path:
    payload = {"controls": controls}
    if extras:
        payload.update(extras)
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(payload))
    return p


def test_parse_returns_keymap_dict(tmp_path):
    p = _write_settings(tmp_path, {"forward": "w", "reverse": "s", "jump": "control"})
    s = parse_ttr_settings(p)
    assert isinstance(s, TtrSettings)
    assert s.controls["forward"] == "w"
    assert s.controls["jump"] == "control"


def test_has_letter_hotkeys_true_when_letter_present(tmp_path):
    p = _write_settings(tmp_path, {"forward": "w", "reverse": "s", "jump": "control"})
    s = parse_ttr_settings(p)
    assert s.has_letter_hotkeys is True


def test_has_letter_hotkeys_false_for_default_arrows(tmp_path):
    p = _write_settings(tmp_path, {
        "forward": "up", "reverse": "down", "left": "left", "right": "right",
        "jump": "control",
    })
    s = parse_ttr_settings(p)
    assert s.has_letter_hotkeys is False


def test_chat_by_typing_resolved_off_when_letters_present(tmp_path):
    """If any control is a letter, TTR's 'chat by typing' is effectively off."""
    p = _write_settings(tmp_path, {"forward": "w"})
    s = parse_ttr_settings(p)
    assert s.chat_by_typing_enabled_resolved is False


def test_chat_by_typing_resolved_on_when_default_arrows(tmp_path):
    p = _write_settings(tmp_path, {"forward": "up"})
    s = parse_ttr_settings(p)
    assert s.chat_by_typing_enabled_resolved is True


def test_resolve_chat_block_list_letters_off_blocks_only_return(tmp_path):
    p = _write_settings(tmp_path, {"forward": "w"})
    s = parse_ttr_settings(p)
    block = resolve_chat_block_list(s)
    assert "Return" in block
    assert "Escape" in block
    assert "a" not in block
    assert "z" not in block


def test_resolve_chat_block_list_letters_on_blocks_all_letters(tmp_path):
    p = _write_settings(tmp_path, {"forward": "up"})
    s = parse_ttr_settings(p)
    block = resolve_chat_block_list(s)
    assert "Return" in block
    for c in "abcdefghijklmnopqrstuvwxyz":
        assert c in block, f"Expected letter '{c}' in block list"


def test_explicit_flag_in_settings_overrides_heuristic(tmp_path):
    """If TTR exposes an explicit chat-by-typing flag in settings.json, honor it.

    NOTE: exact field name is TBD during real-data probing in B.3. The parser
    accepts a tuple of candidate names; this test asserts the override behavior
    works regardless of which candidate the field landed on.
    """
    p = _write_settings(tmp_path, {"forward": "up"}, extras={"chat-by-typing": False})
    s = parse_ttr_settings(p)
    assert s.chat_by_typing_enabled_resolved is False


def test_locate_returns_none_when_no_path_exists(tmp_path, monkeypatch):
    from utils.ttr_settings import locate_settings_file
    monkeypatch.setenv("APPDATA", str(tmp_path / "no-such"))
    monkeypatch.setattr("utils.ttr_settings._FLATPAK_PATH", str(tmp_path / "no-such-flatpak"))
    monkeypatch.setattr("utils.ttr_settings._engine_dir_from_settings", lambda: None)
    assert locate_settings_file() is None
