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
