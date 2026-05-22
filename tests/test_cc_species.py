import pytest

from utils import cc_species


# Provenance: each (letter, species) entry verified via a
# __handleAvatarChooserDone log line from a live CC session on 2026-05-22.
KNOWN_LETTERS = {
    "a": "CROCODILE",   # Little Zippy
    "b": "BEAR",        # Loony Paddlemooch
    "c": "CAT",         # Stylish Cat
    "d": "DOG",         # Flossbud / Incredible Dog
    "e": "KOALA",       # Rowdy Koala
    "f": "DUCK",        # Hector Pepperroni
    "g": "TURKEY",      # Rhinoknees
    "h": "HORSE",       # Peppy Gumdropfink
    "j": "KANGAROO",    # Grumpy Slumpy Fumblecrash
    "k": "KIWI",        # Giggles Weaseltwist
    "l": "ARMADILLO",   # Cookie Jiffycrump
    "m": "MOUSE",       # Soupy
    "n": "BAT",         # Coach Paddlebrains
    "p": "MONKEY",      # Deputy Loony
    "r": "RABBIT",      # Coach Beanscreech
    "s": "PIG",         # Murky Frinkelmarble
    "t": "RACCOON",     # Grumpy Biscuit
    "v": "FOX",         # Lucky Stubby
    "x": "DEER",        # Yippie Poodlethud
    "z": "BEAVER",      # Grouchy Grumblestink
}


@pytest.mark.parametrize("letter,expected_species", list(KNOWN_LETTERS.items()))
def test_known_letters_resolve_to_species(letter, expected_species):
    species, _emoji = cc_species.lookup(letter)
    assert species == expected_species


def test_known_letters_count_matches_full_roster():
    # CC has exactly 20 playable species verified via avatar chooser walk on
    # 2026-05-22. This guard catches accidental removals from the dict.
    assert len(cc_species.HEAD_LETTER_TO_SPECIES) == 20


def test_emoji_lookup_still_works_for_letters_with_emoji_mapping():
    # Backward-compat: lookup() still returns a (species, emoji) tuple.
    # SPECIES_TO_EMOJI is dead code (badge uses PNG icons) - slated for a
    # separate cleanup, asserting two known-mapped letters here is enough.
    assert cc_species.lookup("d") == ("DOG", "\U0001f436")
    assert cc_species.lookup("t") == ("RACCOON", "\U0001f99d")


def test_unknown_letter_returns_question_emoji():
    name, emoji = cc_species.lookup("i")  # 'i' has no playable species in CC
    assert name is None
    assert emoji == "❓"


def test_unknown_letter_logs_once_per_letter(caplog, monkeypatch):
    monkeypatch.setattr(cc_species, "_logged_unknowns", set())
    with caplog.at_level("INFO"):
        cc_species.lookup("q")
        cc_species.lookup("q")  # second call must NOT log again
    assert sum(1 for r in caplog.records if "unknown head letter" in r.message) == 1
