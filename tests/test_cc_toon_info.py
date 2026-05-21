from utils.cc_toon_info import CCToonInfo


def test_cc_toon_info_defaults_are_all_none():
    info = CCToonInfo()
    assert info.name is None
    assert info.head_code is None
    assert info.species_letter is None
    assert info.species_name is None
    assert info.species_emoji is None
    assert info.playground is None
    assert info.zone_name is None
    assert info.dna_colors is None


def test_cc_toon_info_constructs_with_all_fields():
    info = CCToonInfo(
        name="Flossbud",
        head_code="dss",
        species_letter="d",
        species_name="DOG",
        species_emoji="🐶",
        playground="Toontown Central",
        zone_name="Loopy Lane",
        dna_colors=((0.0, 0.4, 0.65), (1.0, 1.0, 1.0), (0.0, 0.4, 0.65),
                    (0.0, 0.4, 0.65), (0.0, 0.4, 0.65)),
    )
    assert info.name == "Flossbud"
    assert info.species_emoji == "🐶"
    assert len(info.dna_colors) == 5
