import pytest
from utils.widgets.keysets import keyboard_data as kd
from utils.key_registry import NAMED_KEY_REGISTRY

CANON = {k.canonical for k in NAMED_KEY_REGISTRY}

def _all_codes(rows):
    return {code for row in rows for cell in row if cell for (code, *_ ) in [cell]}

def test_keycap_codes_use_registry_canonical_for_named_keys():
    codes = _all_codes(kd.KEY_ROWS) | _all_codes(kd.NAV_ROWS)
    for c in ("space", "Up", "Down", "Left", "Right", "Shift_L", "Shift_R",
              "Control_L", "Control_R", "Alt_L", "Alt_R", "BackSpace", "Return",
              "Tab", "Delete", "End", "Next"):
        assert c in codes, f"{c} missing from board"
    assert "w" in codes and "a" in codes and "W" not in codes

def test_assignment_map_keys_by_value():
    s = {"forward": "w", "reverse": "s", "jump": "space"}
    m = kd.assignment_map(s, ["forward", "reverse", "jump"])
    assert m == {"w": "forward", "s": "reverse", "space": "jump"}

def test_conflict_values_finds_duplicates():
    s = {"forward": "w", "gags": "w", "reverse": "s"}
    assert kd.conflict_values(s, ["forward", "gags", "reverse"]) == {"w"}
    assert kd.conflict_values({"a": "w", "b": "s"}, ["a", "b"]) == set()

def test_is_movement():
    assert kd.is_movement("forward") and kd.is_movement("jump")
    assert not kd.is_movement("gags") and not kd.is_movement("sprint")

def test_rows_for_mac_swaps_bottom_row():
    win = kd.rows_for(False)
    mac = kd.rows_for(True)
    assert win[-1] != mac[-1]
    assert any(code == "Meta_L" for (code, *_ ) in mac[-1])

def test_key_label_mac_glyphs():
    assert kd.key_label("BackSpace", "Backspace", mac=False) == "Backspace"
    assert kd.key_label("BackSpace", "Backspace", mac=True) == "⌫"

def test_value_label_mac_remaps_modifiers_only():
    assert kd.value_label("Alt_L", mac=True) == "⌥ Option"
    assert kd.value_label("w", mac=True) == "w"
    assert kd.value_label("Alt_L", mac=False) == "Alt_L"
