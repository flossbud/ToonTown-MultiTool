"""Game classification from X11 window properties (pure, no display needed)."""
from utils.x11_discovery import _game_for_window_props


def test_ttr_via_wm_class():
    # get_wm_class() returns (instance, class); class component carries the name.
    assert _game_for_window_props(["toontown", "Toontown Rewritten"], None) == "ttr"


def test_cc_via_wm_name_prefix_under_proton():
    # CC under Wine/Proton has WM_CLASS forced to steam_proton; the only X11
    # signal of "this is CC" is the WM_NAME prefix.
    assert _game_for_window_props(
        ["steam_proton", "steam_proton"], "Corporate Clash [1.11.17777]"
    ) == "cc"


def test_wine_console_full_path_title_not_matched():
    # The sibling Wine console window's title is the .exe's full Windows path;
    # startswith (not substring) must keep it from matching as CC.
    assert _game_for_window_props(
        ["steam_proton", "steam_proton"],
        r"C:\users\steamuser\AppData\Local\Corporate Clash\CorporateClash.exe",
    ) is None


def test_unrelated_window_is_none():
    assert _game_for_window_props(["firefox", "Firefox"], "Mozilla Firefox") is None


def test_cc_via_wm_class_substring():
    assert _game_for_window_props(["corporateclash", "Corporate Clash"], None) == "cc"


def test_ttr_flatpak_launcher_window_is_not_a_game():
    # The TTR flatpak's launcher UI (/app/bin/toontown) has WM_CLASS
    # "toontown"/"toontown" and title "Toontown Rewritten Launcher". It used to
    # slip through the WM_NAME-prefix fallback and steal a toon slot.
    assert _game_for_window_props(
        ["toontown", "toontown"], "Toontown Rewritten Launcher"
    ) is None


def test_ttr_never_classified_by_title_alone():
    # TTR on Linux is native-only: the engine always sets WM_CLASS class
    # "Toontown Rewritten". The title fallback exists for Wine/Proton CC only.
    assert _game_for_window_props(["foo", "foo"], "Toontown Rewritten") is None


def test_cc_launcher_titled_window_is_not_a_game():
    assert _game_for_window_props(
        ["steam_proton", "steam_proton"], "Corporate Clash Launcher"
    ) is None


def test_cc_bare_title_under_wine_still_matches():
    assert _game_for_window_props(["steam_proton", "steam_proton"], "Corporate Clash") == "cc"
