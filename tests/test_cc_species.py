from utils import cc_species


def test_known_letters_resolve_to_species_and_emoji():
    # Verified from user-confirmed observations:
    #   d→DOG (Flossbud, Incredible Dog)
    #   f→DUCK (Hector Pepperroni)
    #   m→MOUSE (Soupy)
    #   e→KOALA (Rowdy Koala)
    assert cc_species.lookup("d") == ("DOG", "🐶")
    assert cc_species.lookup("f") == ("DUCK", "🦆")
    assert cc_species.lookup("m") == ("MOUSE", "🐭")
    assert cc_species.lookup("e") == ("KOALA", "🐨")


def test_unknown_letter_returns_question_emoji():
    name, emoji = cc_species.lookup("z")
    assert name is None
    assert emoji == "❓"


def test_unknown_letter_logs_once_per_letter(caplog, monkeypatch):
    # Reset the logged-set so the test is hermetic
    monkeypatch.setattr(cc_species, "_logged_unknowns", set())
    with caplog.at_level("INFO"):
        cc_species.lookup("q")
        cc_species.lookup("q")  # second call must NOT log again
    assert sum(1 for r in caplog.records if "unknown head letter" in r.message) == 1
