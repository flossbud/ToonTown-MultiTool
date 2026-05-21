"""Tests for the title-suffix matcher used to identify CC's Wine console."""

from services.wine_console_hider import _title_matches


def test_matches_canonical_backslash_title():
    title = r"C:\users\steamuser\AppData\Local\Corporate Clash\CorporateClash.exe"
    assert _title_matches(title) is True


def test_matches_forward_slash_title():
    title = "C:/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    assert _title_matches(title) is True


def test_matches_mixed_case_extension():
    title = r"C:\users\steamuser\AppData\Local\Corporate Clash\CorporateClash.EXE"
    assert _title_matches(title) is True


def test_matches_mixed_case_basename():
    title = r"C:\foo\CORPORATECLASH.exe"
    assert _title_matches(title) is True


def test_does_not_match_game_window_title():
    """The actual game window is titled `Corporate Clash [<version>]` with
    NO .exe suffix; must not be falsely matched."""
    assert _title_matches("Corporate Clash [1.11.17777]") is False


def test_does_not_match_unrelated_titles():
    assert _title_matches("Firefox") is False
    assert _title_matches("") is False
    assert _title_matches("CorporateClash.exe.txt") is False


def test_does_not_match_when_path_ends_in_other_exe():
    assert _title_matches(r"C:\foo\new_launcher.exe") is False
