"""ttr_dna.parse_dna - species from the packed ToonDNA hex.

Samples are real strings from a live config; their species were confirmed by
reading each toon's cached Rendition portrait (see the plan Task 1 probe).
"""
from utils.ttr_dna import parse_dna
from utils.cc_race_assets import asset_stem_for_species

# name -> (dna, confirmed species) from the live-config probe
SAMPLES = {
    "Hiro":     ("740001010108200820090214000808010400202b00000000000000202c00011200", "DOG"),
    "Katsuro":  ("7405010201e41bcc1bb81b12001212010400000000040000016000000000010100", "CAT"),
    "Moe":      ("74090202015f1b541b361b080008080104002a00000e0000000000120000012b00", "HORSE"),
    "Roboroni": ("740d0202015f1b541b5110240024240104000000000e0000000000090000012e00", "MOUSE"),
    "Bubblegum":("7410020201041c041c091b28002828010400000000000000000000000000000000", "RABBIT"),
}


def test_parse_species_matches_confirmed_portraits():
    for name, (dna, species) in SAMPLES.items():
        got, accent = parse_dna(dna)
        assert got == species, f"{name}: expected {species}, got {got}"
        assert accent is None  # no in-repo palette; live headColor is authoritative


def test_species_all_map_to_a_race_asset():
    for _name, (dna, _species) in SAMPLES.items():
        species, _ = parse_dna(dna)
        assert asset_stem_for_species(species) is not None


def test_head_index_covers_every_species():
    # one representative head byte per animal -> its species
    expected = {0: "DOG", 4: "CAT", 8: "HORSE", 12: "MOUSE", 14: "RABBIT",
                18: "DUCK", 22: "MONKEY", 26: "BEAR", 30: "PIG"}
    for head, species in expected.items():
        dna = "74" + f"{head:02x}" + "00" * 12  # type + head + padding
        assert parse_dna(dna)[0] == species


def test_rejects_garbage():
    assert parse_dna("") == (None, None)
    assert parse_dna("not-hex") == (None, None)
    assert parse_dna("ffff") == (None, None)       # wrong type byte
    assert parse_dna("74") == (None, None)         # too short (no head byte)
    assert parse_dna("74ff" + "00" * 12) == (None, None)  # head index out of range
