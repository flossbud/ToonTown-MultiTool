"""WindowManager per-game window counting."""
from services.window_manager import WindowManager


def test_count_for_game_reads_window_games_map():
    wm = WindowManager(settings_manager=None)
    wm.window_games = {"100": "cc", "200": "cc", "300": "ttr"}
    assert wm.count_for_game("cc") == 2
    assert wm.count_for_game("ttr") == 1
    assert wm.count_for_game("nonexistent") == 0


def test_assign_windows_populates_games_linux(monkeypatch):
    # Pin the platform so this exercises the Linux x11 discovery branch on any
    # host (the macOS dev box would otherwise take the new darwin branch and
    # bypass the x11_discovery monkeypatches below).
    import sys
    monkeypatch.setattr(sys, "platform", "linux")

    from utils import x11_discovery
    from utils.game_registry import GameRegistry

    monkeypatch.setattr(
        x11_discovery, "find_game_windows",
        lambda: [("100", "cc"), ("200", "ttr")],
    )
    monkeypatch.setattr(
        x11_discovery, "get_window_root_x",
        lambda wid: {"100": 10, "200": 20}.get(wid),
    )
    monkeypatch.setattr(
        GameRegistry.instance(), "classify_window_for_filtering",
        lambda wid: (None, False),
    )

    wm = WindowManager(settings_manager=None)
    wm._detection_enabled = True
    wm.assign_windows()

    assert set(wm.ttr_window_ids) == {"100", "200"}
    assert wm.count_for_game("cc") == 1
    assert wm.count_for_game("ttr") == 1
