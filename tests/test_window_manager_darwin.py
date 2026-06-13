"""Tests for darwin branches in services/window_manager.py."""
import importlib

wm = importlib.import_module("services.window_manager")


def test_geometry_backend_darwin(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    assert wm._geometry_backend() is macos_discovery


def test_assign_windows_darwin_sort(monkeypatch):
    """darwin enumeration branch sorts windows left-to-right by root-x."""
    from utils import macos_discovery
    from utils.game_registry import GameRegistry
    from services.window_manager import WindowManager

    # Patch platform so the darwin branch is taken on any host OS.
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)

    # Two TTR windows: "11" is far right (x=100), "33" is far left (x=5).
    monkeypatch.setattr(
        macos_discovery, "find_game_windows",
        lambda: [("11", "ttr"), ("33", "ttr")],
    )
    root_x_map = {"11": 100, "33": 5}
    monkeypatch.setattr(
        macos_discovery, "get_window_root_x",
        lambda wid: root_x_map.get(wid),
    )
    # classify_window_for_filtering returns (game="ttr", confirmed=True), so
    # _accept_candidate_window (`not confirmed or game is not None`) is True for
    # both windows.
    monkeypatch.setattr(
        GameRegistry.instance(), "classify_window_for_filtering",
        lambda wid: ("ttr", True),
    )

    wm_inst = WindowManager(settings_manager=None)
    wm_inst._detection_enabled = True
    wm_inst.assign_windows()

    # "33" (x=5) must sort before "11" (x=100).
    assert wm_inst.ttr_window_ids == ["33", "11"]
    assert wm_inst.window_games == {"33": "ttr", "11": "ttr"}
