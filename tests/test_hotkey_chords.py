"""Chord model: canonical strings, guardrails, X mask compilation."""
import pytest

from utils.hotkey_chords import (
    Chord, parse_chord, format_chord, chord_error, MOD_MASKS, x_modmask,
)


def test_parse_roundtrip_and_canonical_order():
    c = parse_chord("alt+ctrl+H")
    assert c == Chord(mods=frozenset({"ctrl", "alt"}), keys=frozenset({"h"}))
    assert format_chord(c) == "ctrl+alt+h"          # canonical mod order, lower key


def test_parse_fkey_and_super():
    assert parse_chord("F5") == Chord(mods=frozenset(), keys=frozenset({"F5"}))
    assert parse_chord("super+F2") == Chord(mods=frozenset({"super"}),
                                            keys=frozenset({"F2"}))


def test_parse_rejects_garbage():
    for bad in ("", "ctrl+", "ctrl+alt", "ctrl+a+b+c"):
        with pytest.raises(ValueError):
            parse_chord(bad)


def test_guardrail_bare_key_needs_fkey():
    assert chord_error(parse_chord("f5".upper())) is None
    assert chord_error(parse_chord("ctrl+1")) is None
    err = chord_error(parse_chord("h"))
    assert err is not None and "modifier" in err.lower()
    assert chord_error(parse_chord("1")) is not None


def test_parse_multikey_roundtrip_sorted():
    c = parse_chord("shift+t+1")
    assert c == Chord(mods=frozenset({"shift"}), keys=frozenset({"t", "1"}))
    assert format_chord(c) == "shift+1+t"           # keys sorted
    assert parse_chord("shift+1+t") == c            # order-insensitive


def test_parse_rejects_three_keys_and_duplicates():
    with pytest.raises(ValueError):
        parse_chord("ctrl+a+b+c")
    with pytest.raises(ValueError):
        parse_chord("ctrl+t+t")
    with pytest.raises(ValueError):
        parse_chord("ctrl+T+t")                     # dup after canonicalization


def test_multikey_guardrail_needs_modifier():
    err = chord_error(parse_chord("t+1"))
    assert err is not None and "modifier" in err.lower()
    assert chord_error(parse_chord("shift+t+1")) is None
    err = chord_error(parse_chord("F5+F6"))          # multi-key F-keys too
    assert err is not None


def test_single_key_compat_accessor():
    c = parse_chord("ctrl+h")
    assert c.key == "h"                              # legacy single-key access
    with pytest.raises(ValueError):
        _ = parse_chord("shift+t+1").key             # ambiguous on multi


def test_mod_masks_cover_all_four():
    assert set(MOD_MASKS) == {"ctrl", "shift", "alt", "super"}


def test_x_modmask_composition():
    assert MOD_MASKS == {"shift": 1, "ctrl": 4, "alt": 8, "super": 64}
    assert x_modmask(parse_chord("ctrl+alt+h")) == 12
