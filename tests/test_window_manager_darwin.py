"""Tests for darwin branches in services/window_manager.py."""
import importlib

wm = importlib.import_module("services.window_manager")


def test_geometry_backend_darwin(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    assert wm._geometry_backend() is macos_discovery


def test_assign_windows_darwin_orders_by_cell(monkeypatch):
    """darwin enumeration orders windows by 2x2 cell; a side-by-side pair still
    reads left-to-right (left -> cell 0, right -> cell 1)."""
    from utils import macos_discovery
    from utils.game_registry import GameRegistry
    from services.window_manager import WindowManager

    # Patch platform so the darwin branch (and _geometry_backend) is taken.
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)

    # Two TTR windows side by side: "11" far right, "33" far left (same y).
    monkeypatch.setattr(
        macos_discovery, "find_game_windows",
        lambda: [("11", "ttr"), ("33", "ttr")],
    )
    geoms = {"11": (100, 0, 50, 50), "33": (5, 0, 50, 50)}  # centers (125,25),(30,25)
    monkeypatch.setattr(
        macos_discovery, "get_window_geometry",
        lambda wid: geoms.get(wid),
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

    # Left window "33" -> cell 0, right window "11" -> cell 1.
    assert wm_inst.ttr_window_ids == ["33", "11"]
    assert wm_inst.window_games == {"33": "ttr", "11": "ttr"}
