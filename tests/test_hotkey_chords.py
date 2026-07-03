"""Chord model: canonical strings, guardrails, X mask compilation."""
import pytest

from utils.hotkey_chords import (
    Chord, parse_chord, format_chord, chord_error, MOD_MASKS, x_modmask,
)


def test_parse_roundtrip_and_canonical_order():
    c = parse_chord("alt+ctrl+H")
    assert c == Chord(mods=frozenset({"ctrl", "alt"}), key="h")
    assert format_chord(c) == "ctrl+alt+h"          # canonical mod order, lower key


def test_parse_fkey_and_super():
    assert parse_chord("F5") == Chord(mods=frozenset(), key="F5")
    assert parse_chord("super+F2") == Chord(mods=frozenset({"super"}), key="F2")


def test_parse_rejects_garbage():
    for bad in ("", "ctrl+", "ctrl+alt", "ctrl+h+j", "hyper+h"):
        with pytest.raises(ValueError):
            parse_chord(bad)


def test_guardrail_bare_key_needs_fkey():
    assert chord_error(parse_chord("f5".upper())) is None
    assert chord_error(parse_chord("ctrl+1")) is None
    err = chord_error(parse_chord("h"))
    assert err is not None and "modifier" in err.lower()
    assert chord_error(parse_chord("1")) is not None


def test_mod_masks_cover_all_four():
    assert set(MOD_MASKS) == {"ctrl", "shift", "alt", "super"}


def test_x_modmask_composition():
    assert MOD_MASKS == {"shift": 1, "ctrl": 4, "alt": 8, "super": 64}
    assert x_modmask(parse_chord("ctrl+alt+h")) == 12
