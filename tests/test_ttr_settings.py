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


def test_locate_returns_path_for_engine_dir(tmp_path, monkeypatch):
    """Positive-hit: when an explicit engine_dir is passed and the file exists,
    locate_settings_file returns it without consulting the other candidates."""
    from utils.ttr_settings import locate_settings_file
    (tmp_path / "settings.json").write_text("{}")
    # Make the lower-priority candidates unreachable so the test fails loudly
    # if priority order ever regresses.
    monkeypatch.setenv("APPDATA", str(tmp_path / "no-such"))
    monkeypatch.setattr("utils.ttr_settings._FLATPAK_PATH", str(tmp_path / "no-such-flatpak"))
    monkeypatch.setattr("utils.ttr_settings._engine_dir_from_settings", lambda: None)
    result = locate_settings_file(engine_dir=str(tmp_path))
    assert result == tmp_path / "settings.json"


class _FakeKeymapManager:
    def __init__(self):
        self.calls = []

    def update_set_key(self, game, set_index, action, keysym):
        self.calls.append((game, set_index, action, keysym))


def test_apply_ttr_controls_to_set_translates_arrows_and_control():
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    controls = {
        "forward": "up", "reverse": "down", "left": "left", "right": "right",
        "jump": "control",
    }
    n = apply_ttr_controls_to_set(km, 0, controls)
    assert n == 5
    assert all(call[0] == "ttr" for call in km.calls)
    by_action = {action: k for (_, _, action, k) in km.calls}
    assert by_action["forward"] == "Up"
    assert by_action["reverse"] == "Down"
    assert by_action["left"] == "Left"
    assert by_action["right"] == "Right"
    assert by_action["jump"] == "Control_L"


def test_apply_ttr_controls_to_set_passes_through_letter_hotkeys():
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    n = apply_ttr_controls_to_set(km, 0, {"forward": "w", "reverse": "s"})
    assert n == 2
    assert all(call[0] == "ttr" for call in km.calls)
    by_action = {action: k for (_, _, action, k) in km.calls}
    assert by_action["forward"] == "w"
    assert by_action["reverse"] == "s"


def test_apply_ttr_controls_to_set_skips_missing_keys():
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    # Only "jump" present; the rest should be skipped.
    n = apply_ttr_controls_to_set(km, 1, {"jump": "control"})
    assert n == 1
    assert km.calls == [("ttr", 1, "jump", "Control_L")]


def test_apply_ttr_controls_to_set_translates_default_arrow_aliases():
    """TTR's settings.json uses 'arrow_up'/'arrow_down'/'arrow_left'/'arrow_right'
    for the default movement bindings — NOT the bare 'up'/'down'/'left'/'right'
    that the original _TTR_VALUE_TO_KEYSYM table covered.

    Confirmed by reading a real settings.json from a clean Windows TTR install:
        "forward": "arrow_up",
        "reverse": "arrow_down",
        "left":    "arrow_left",
        "right":   "arrow_right",
        "jump":    "control",
    Without this test, auto-detect wrote raw 'arrow_up' strings into the
    keymap, causing user-reported issue: arrow forwarding completely
    nonfunctional under default TTR.
    """
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    controls = {
        "forward": "arrow_up",
        "reverse": "arrow_down",
        "left":    "arrow_left",
        "right":   "arrow_right",
        "jump":    "control",
    }
    n = apply_ttr_controls_to_set(km, 0, controls)
    assert n == 5
    assert all(call[0] == "ttr" for call in km.calls)
    by_action = {action: k for (_, _, action, k) in km.calls}
    assert by_action["forward"] == "Up", f"forward=arrow_up must translate to Up keysym, got {by_action['forward']!r}"
    assert by_action["reverse"] == "Down"
    assert by_action["left"] == "Left"
    assert by_action["right"] == "Right"
    assert by_action["jump"] == "Control_L"


def test_apply_ttr_controls_to_set_translates_nav_cluster_and_f_keys():
    """TTR's default controls also include home/end/f8 for showGags/showTasks/
    stickerBook. Without these in _TTR_VALUE_TO_KEYSYM, the keymap is
    populated with raw 'home'/'f8' strings that match nothing downstream."""
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    controls = {
        "stickerBook": "f8",
        "showGags": "home",
        "showTasks": "end",
        "showMap":  "alt",
    }
    n = apply_ttr_controls_to_set(km, 0, controls)
    assert n == 4
    assert all(call[0] == "ttr" for call in km.calls)
    by_action = {action: k for (_, _, action, k) in km.calls}
    assert by_action["book"] == "F8", f"f8 must translate to F8 keysym, got {by_action['book']!r}"
    assert by_action["gags"] == "Home"
    assert by_action["tasks"] == "End"
    assert by_action["map"] == "Alt_L"


def test_apply_ttr_controls_to_set_translates_page_keys_and_insert():
    """TTR can bind lookUp/lookDown to page_up/page_down by default."""
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    # No direction in TTMT maps to lookUp/lookDown today, but if/when
    # TTR's settings.json puts page_up etc. into one of TTMT's 9 tracked
    # control fields, we must translate it. Use 'jump' as the carrier so
    # the assertion is exercised.
    controls = {"jump": "page_up"}
    n = apply_ttr_controls_to_set(km, 0, controls)
    assert n == 1
    assert km.calls[0] == ("ttr", 0, "jump", "Prior")


def test_apply_ttr_controls_to_set_translates_insert_and_other_function_keys():
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    controls = {"jump": "insert", "stickerBook": "f12"}
    n = apply_ttr_controls_to_set(km, 0, controls)
    assert all(call[0] == "ttr" for call in km.calls)
    by_action = {action: k for (_, _, action, k) in km.calls}
    assert by_action["jump"] == "Insert"
    assert by_action["book"] == "F12"


def test_has_letter_hotkeys_false_for_real_ttr_default_arrows(tmp_path):
    """Regression guard: a real TTR default settings.json (with 'arrow_up'
    etc.) must resolve to has_letter_hotkeys=False, so chat-by-typing is
    inferred ON and the chat-block list includes letters."""
    from utils.ttr_settings import parse_ttr_settings, resolve_chat_block_list
    p = _write_settings(tmp_path, {
        "forward": "arrow_up", "reverse": "arrow_down",
        "left": "arrow_left", "right": "arrow_right",
        "jump": "control", "showMap": "alt",
        "stickerBook": "f8", "showGags": "home", "showTasks": "end",
    })
    s = parse_ttr_settings(p)
    assert s.has_letter_hotkeys is False
    assert s.chat_by_typing_enabled_resolved is True
    assert "a" in resolve_chat_block_list(s)


def test_apply_ttr_controls_to_set_translates_perform_action_delete():
    """TTR's `performAction` field (default key `delete` on a clean
    install) maps to the TTMT `action` logical action. The string `delete`
    translates to the X11 keysym name `Delete`."""
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    n = apply_ttr_controls_to_set(km, 0, {"performAction": "delete"})
    assert n == 1
    assert km.calls == [("ttr", 0, "action", "Delete")]


def test_apply_ttr_controls_to_set_translates_perform_action_backslash():
    """TTR's JSON writes performAction as the raw char '\\'. That raw char
    must be stored verbatim in the keymap so it matches what pynput delivers
    at runtime. _resolve_keysym('\\') converts to the X11 keysym at send
    time; the keymap must never store the X11 name 'backslash' directly."""
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    n = apply_ttr_controls_to_set(km, 0, {"performAction": "\\"})
    assert n == 1
    assert km.calls == [("ttr", 0, "action", "\\")]


def test_apply_ttr_controls_to_set_perform_action_letter_passes_through():
    """A TTR user who has remapped `performAction` to a single letter
    (e.g. `u`); the letter passes through verbatim, same as other
    letter-hotkey controls."""
    from utils.ttr_settings import apply_ttr_controls_to_set
    km = _FakeKeymapManager()
    n = apply_ttr_controls_to_set(km, 0, {"performAction": "u"})
    assert n == 1
    assert km.calls == [("ttr", 0, "action", "u")]
