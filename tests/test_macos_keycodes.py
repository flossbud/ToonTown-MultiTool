"""Tests for utils.macos_keycodes — X11 keysym <-> macOS CGKeyCode mapping.

Pure data + lookups; runs on any interpreter (no PyObjC import).
"""

import pytest

from utils import macos_keycodes as mk
from utils.key_registry import NAMED_KEY_REGISTRY


# ── Movement / letters ──────────────────────────────────────────────────────

def test_movement_letters():
    assert mk.cgkeycode_for_keysym("w") == 0x0D
    assert mk.cgkeycode_for_keysym("a") == 0x00
    assert mk.cgkeycode_for_keysym("s") == 0x01
    assert mk.cgkeycode_for_keysym("d") == 0x02


def test_single_char_case_insensitive():
    assert mk.cgkeycode_for_keysym("W") == mk.cgkeycode_for_keysym("w") == 0x0D
    assert mk.cgkeycode_for_keysym("Q") == mk.cgkeycode_for_keysym("q") == 0x0C


def test_digits():
    assert mk.cgkeycode_for_keysym("1") == 0x12
    assert mk.cgkeycode_for_keysym("0") == 0x1D
    assert mk.cgkeycode_for_keysym("5") == 0x17


# ── Named keys + Prior/Next aliases ─────────────────────────────────────────

def test_named_keys():
    assert mk.cgkeycode_for_keysym("Up") == 0x7E
    assert mk.cgkeycode_for_keysym("Down") == 0x7D
    assert mk.cgkeycode_for_keysym("Left") == 0x7B
    assert mk.cgkeycode_for_keysym("Right") == 0x7C
    assert mk.cgkeycode_for_keysym("Return") == 0x24
    assert mk.cgkeycode_for_keysym("Escape") == 0x35
    assert mk.cgkeycode_for_keysym("space") == 0x31
    assert mk.cgkeycode_for_keysym("Tab") == 0x30
    assert mk.cgkeycode_for_keysym("BackSpace") == 0x33
    assert mk.cgkeycode_for_keysym("Delete") == 0x75


def test_prior_next_aliases():
    # X11 'Prior'/'Next' are Page_Up/Page_Down.
    assert mk.cgkeycode_for_keysym("Prior") == 0x74
    assert mk.cgkeycode_for_keysym("Next") == 0x79
    assert mk.cgkeycode_for_keysym("Page_Up") == 0x74
    assert mk.cgkeycode_for_keysym("Page_Down") == 0x79
    assert mk.cgkeycode_for_keysym("Home") == 0x73
    assert mk.cgkeycode_for_keysym("End") == 0x77
    assert mk.cgkeycode_for_keysym("Insert") == 0x72


def test_function_keys():
    assert mk.cgkeycode_for_keysym("F1") == 0x7A
    assert mk.cgkeycode_for_keysym("F5") == 0x60
    assert mk.cgkeycode_for_keysym("F12") == 0x6F


def test_numpad():
    assert mk.cgkeycode_for_keysym("KP_0") == 0x52
    assert mk.cgkeycode_for_keysym("KP_9") == 0x5C
    assert mk.cgkeycode_for_keysym("KP_Enter") == 0x4C
    assert mk.cgkeycode_for_keysym("KP_Decimal") == 0x41
    assert mk.cgkeycode_for_keysym("KP_Add") == 0x45
    assert mk.cgkeycode_for_keysym("KP_Divide") == 0x4B


def test_punctuation():
    assert mk.cgkeycode_for_keysym("minus") == 0x1B
    assert mk.cgkeycode_for_keysym("equal") == 0x18
    assert mk.cgkeycode_for_keysym("bracketleft") == 0x21
    assert mk.cgkeycode_for_keysym("grave") == 0x32


# ── Modifiers: both a CGKeyCode and a flag ──────────────────────────────────

def test_modifiers_have_keycode_and_flag():
    cases = {
        "Shift_L": (0x38, mk.FLAG_SHIFT),
        "Shift_R": (0x3C, mk.FLAG_SHIFT),
        "Control_L": (0x3B, mk.FLAG_CONTROL),
        "Control_R": (0x3E, mk.FLAG_CONTROL),
        "Alt_L": (0x3A, mk.FLAG_OPTION),
        "Alt_R": (0x3D, mk.FLAG_OPTION),
    }
    for keysym, (vk, flag) in cases.items():
        assert mk.cgkeycode_for_keysym(keysym) == vk, keysym
        assert mk.flag_for_modifier_keysym(keysym) == flag, keysym


def test_flag_constants():
    assert mk.FLAG_SHIFT == 0x00020000
    assert mk.FLAG_CONTROL == 0x00040000
    assert mk.FLAG_OPTION == 0x00080000
    assert mk.FLAG_COMMAND == 0x00100000


def test_meta_super_flags():
    assert mk.flag_for_modifier_keysym("Meta") == mk.FLAG_OPTION
    assert mk.flag_for_modifier_keysym("Super") == mk.FLAG_COMMAND


def test_flag_for_non_modifier_is_none():
    assert mk.flag_for_modifier_keysym("w") is None
    assert mk.flag_for_modifier_keysym("Up") is None


# ── Unknowns ────────────────────────────────────────────────────────────────

def test_unknown_keysym_returns_none():
    assert mk.cgkeycode_for_keysym("NoSuchKey") is None
    assert mk.cgkeycode_for_keysym("") is None


def test_unknown_vk_returns_none():
    assert mk.keysym_for_cgkeycode(0xFFFF) is None


# ── flags_for_modifiers ─────────────────────────────────────────────────────

def test_flags_for_modifiers_or():
    val = mk.flags_for_modifiers(["Shift_L", "Control_L"])
    assert val == (mk.FLAG_SHIFT | mk.FLAG_CONTROL)


def test_flags_for_modifiers_empty_and_none():
    assert mk.flags_for_modifiers([]) == 0
    assert mk.flags_for_modifiers(None) == 0


def test_flags_for_modifiers_ignores_non_modifiers():
    assert mk.flags_for_modifiers(["w", "Up"]) == 0
    assert mk.flags_for_modifiers(["Shift_L", "w"]) == mk.FLAG_SHIFT


# ── Roundtrip ───────────────────────────────────────────────────────────────

def test_roundtrip():
    vk = mk.cgkeycode_for_keysym("w")
    assert mk.keysym_for_cgkeycode(vk) == "w"


# ── CONTRACT: full key-registry inventory coverage ──────────────────────────

def test_contract_full_registry_coverage():
    for kd in NAMED_KEY_REGISTRY:
        primary = kd.keysyms[0]
        if primary in mk.UNSUPPORTED_KEYSYMS:
            # documented gap
            continue
        if kd.category == "modifier":
            # Modifiers need BOTH a CGKeyCode and a flag.
            assert mk.cgkeycode_for_keysym(primary) is not None, primary
            assert mk.flag_for_modifier_keysym(primary) is not None, primary
        else:
            assert mk.cgkeycode_for_keysym(primary) is not None, primary
