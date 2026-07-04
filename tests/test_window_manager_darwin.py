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


# ── is_multitool_active: frontmost-PID fact off Linux ─────────────────────────
# darwin/win32: the multitool_window_id id-compare is a dead path (capture is
# xdotool/X11-only; darwin _active_id only ever holds game ids), so the poll
# loop's frontmost-PID fact decides. Linux keeps the id-compare.

def _wm_inst():
    from services.window_manager import WindowManager
    return WindowManager(settings_manager=None)


def test_is_multitool_active_darwin_reads_self_frontmost(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)
    inst = _wm_inst()
    inst._self_frontmost = True
    assert inst.is_multitool_active() is True
    assert inst.should_capture_input() is True  # hotkeys live while self-focused
    inst._self_frontmost = False
    assert inst.is_multitool_active() is False


def test_is_multitool_active_win32_reads_self_frontmost(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "win32", raising=False)
    inst = _wm_inst()
    inst._self_frontmost = True
    assert inst.is_multitool_active() is True
    inst._self_frontmost = False
    assert inst.is_multitool_active() is False


def test_is_multitool_active_linux_keeps_id_compare(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "linux", raising=False)
    inst = _wm_inst()
    inst.multitool_id = "123"
    inst._active_id = "123"
    inst._self_frontmost = False  # ignored on Linux
    assert inst.is_multitool_active() is True
    inst._active_id = "456"
    inst._self_frontmost = True  # still ignored
    assert inst.is_multitool_active() is False


def test_disable_detection_clears_self_frontmost(monkeypatch):
    monkeypatch.setattr(wm.sys, "platform", "darwin", raising=False)
    inst = _wm_inst()
    inst._self_frontmost = True
    inst.disable_detection()
    assert inst.is_multitool_active() is False
