"""WindowManager geometry cache, with the platform geometry backend
faked out at the dispatch seam (NOT x11_discovery directly: on Windows
the dispatch routes to win32_discovery, so a direct x11 patch silently
misses — found by the first on-box run of this file)."""
import types

from services import window_manager as wm_mod
from services.window_manager import WindowManager


def _fake_backend(monkeypatch, fn):
    """Route _geometry_backend() to a fake on every platform."""
    monkeypatch.setattr(
        wm_mod, "_geometry_backend",
        lambda: types.SimpleNamespace(get_window_geometry=fn))


def test_geometry_cache_refresh_and_get(monkeypatch):
    geoms = {"10": (0, 0, 1280, 720), "20": (1300, 0, 1920, 1080)}
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    wm.ttr_window_ids = ["10", "20"]
    wm.refresh_geometry()
    assert wm.get_window_geometry("10") == (0, 0, 1280, 720)
    assert wm.get_window_geometry("20") == (1300, 0, 1920, 1080)


def test_geometry_change_emits_signal(monkeypatch):
    geoms = {"10": (0, 0, 1280, 720)}
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    wm.ttr_window_ids = ["10"]
    fired = []
    wm.window_geometry_updated.connect(lambda: fired.append(1))
    wm.refresh_geometry()          # first fill: change -> signal
    wm.refresh_geometry()          # same data: no signal
    geoms["10"] = (0, 0, 1280, 1024)
    wm.refresh_geometry()          # resize: signal
    assert len(fired) == 2


def test_geometry_get_falls_back_to_live_query_and_caches_tracked(monkeypatch):
    _fake_backend(monkeypatch, lambda wid: (5, 6, 700, 500))
    wm = WindowManager()
    wm.ttr_window_ids = ["99"]
    # Not in cache: on-demand query, cached because tracked.
    assert wm.get_window_geometry("99") == (5, 6, 700, 500)
    assert wm.window_geometry["99"] == (5, 6, 700, 500)


def test_geometry_fallback_does_not_cache_untracked(monkeypatch):
    _fake_backend(monkeypatch, lambda wid: (5, 6, 700, 500))
    wm = WindowManager()
    # "99" is not tracked: live value returned but never cached.
    assert wm.get_window_geometry("99") == (5, 6, 700, 500)


# --- 2x2 cell ordering (position-based card placement) --------------------
def test_order_wids_by_cell_maps_each_window_to_its_quadrant(monkeypatch):
    geoms = {
        "10": (0, 0, 100, 100),      # center (50,50)   TL
        "20": (200, 0, 100, 100),    # center (250,50)  TR
        "30": (0, 200, 100, 100),    # center (50,250)  BL
        "40": (200, 200, 100, 100),  # center (250,250) BR
    }
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    # Scrambled detection order -> reading order by cell (TL, TR, BL, BR).
    assert wm._order_wids_by_cell(["30", "10", "40", "20"]) == ["10", "20", "30", "40"]


def test_order_wids_by_cell_dedups_and_keeps_unknown_geometry_last(monkeypatch):
    geoms = {"10": (0, 0, 100, 100), "20": (200, 0, 100, 100)}  # "30" has none
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    # Duplicate "10" deduped; "10","20" placed (top row); "30" (no geometry) last.
    assert wm._order_wids_by_cell(["10", "20", "30", "10"]) == ["10", "20", "30"]


def test_order_wids_by_cell_empty(monkeypatch):
    _fake_backend(monkeypatch, lambda wid: None)
    wm = WindowManager()
    assert wm._order_wids_by_cell([]) == []


def test_assign_cells_identity_for_full_grid(monkeypatch):
    geoms = {
        "10": (0, 0, 100, 100), "20": (200, 0, 100, 100),
        "30": (0, 200, 100, 100), "40": (200, 200, 100, 100),
    }
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    ordered, slot_cells = wm._assign_cells_to_wids(["30", "10", "40", "20"])
    assert ordered == ["10", "20", "30", "40"]
    assert slot_cells == [0, 1, 2, 3]   # contiguous -> identity permutation


def test_assign_cells_vertical_stack_gives_left_column_permutation(monkeypatch):
    geoms = {"10": (0, 0, 100, 100), "20": (0, 200, 100, 100)}  # top, bottom (same x)
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    ordered, slot_cells = wm._assign_cells_to_wids(["10", "20"])
    assert ordered == ["10", "20"]       # top (cell 0), bottom (cell 2)
    assert slot_cells == [0, 2, 1, 3]    # slot0->TL, slot1->BL; empties 1,3


def test_assign_windows_emits_cell_assignment_changed_on_stack(monkeypatch):
    from utils.game_registry import GameRegistry
    from utils import x11_discovery
    monkeypatch.setattr(wm_mod.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(x11_discovery, "find_game_windows",
                        lambda: [("10", "ttr"), ("20", "ttr")])
    geoms = {"10": (0, 0, 100, 100), "20": (0, 200, 100, 100)}  # vertical stack
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    monkeypatch.setattr(GameRegistry.instance(), "classify_window_for_filtering",
                        lambda wid: ("ttr", True))
    wm = WindowManager()
    wm._detection_enabled = True
    fired = []
    wm.cell_assignment_changed.connect(lambda cells: fired.append(cells))
    wm.assign_windows()
    assert wm.slot_cells == [0, 2, 1, 3]
    assert fired == [[0, 2, 1, 3]]
    assert "99" not in wm.window_geometry


def test_geometry_removed_window_fires_signal_and_purges(monkeypatch):
    # Removal is the load-bearing trigger for the live mismatch PAUSE:
    # a member window disappearing must fire the change signal.
    geoms = {"10": (0, 0, 1280, 720), "20": (1300, 0, 1920, 1080)}
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    wm.ttr_window_ids = ["10", "20"]
    wm.refresh_geometry()
    fired = []
    wm.window_geometry_updated.connect(lambda: fired.append(1))
    wm.ttr_window_ids = ["10"]  # window 20 disappeared
    wm.refresh_geometry()
    assert len(fired) == 1
    assert "20" not in wm.window_geometry


def test_disable_detection_clears_geometry(monkeypatch):
    geoms = {"10": (0, 0, 100, 100)}
    _fake_backend(monkeypatch, lambda wid: geoms.get(wid))
    wm = WindowManager()
    wm.ttr_window_ids = ["10"]
    wm.refresh_geometry()
    assert wm.window_geometry
    wm.disable_detection()
    assert wm.window_geometry == {}


def test_refresh_commit_guard_after_concurrent_disable(monkeypatch):
    # disable_detection() landing DURING the off-lock X queries must not be
    # overwritten by the refresh's commit (stale-repopulation race).
    geoms = {"10": (0, 0, 100, 100)}
    wm = WindowManager()
    wm.ttr_window_ids = ["10"]

    def query_and_disable(wid):
        wm.disable_detection()  # simulates the race mid-refresh
        return geoms.get(wid)

    _fake_backend(monkeypatch, query_and_disable)
    wm.refresh_geometry()
    assert wm.window_geometry == {}


def test_geometry_unknown_window_none(monkeypatch):
    _fake_backend(monkeypatch, lambda wid: None)
    wm = WindowManager()
    assert wm.get_window_geometry("nope") is None


# ── platform dispatch (Windows port) ───────────────────────────────────

def test_geometry_backend_dispatches_by_platform(monkeypatch):
    from services import window_manager as wm_mod
    monkeypatch.setattr(wm_mod.sys, "platform", "win32")
    from utils import win32_discovery
    assert wm_mod._geometry_backend() is win32_discovery
    monkeypatch.setattr(wm_mod.sys, "platform", "linux")
    from utils import x11_discovery
    assert wm_mod._geometry_backend() is x11_discovery


def test_refresh_geometry_runs_on_win32(monkeypatch):
    """The Linux-only early return is gone: on win32 the cache fills from
    the platform backend and the signal fires."""
    from services import window_manager as wm_mod
    monkeypatch.setattr(wm_mod.sys, "platform", "win32")
    from utils import win32_discovery
    monkeypatch.setattr(win32_discovery, "get_window_geometry",
                        lambda wid: (961, 31, 958, 1008))
    wm = wm_mod.WindowManager()
    wm.ttr_window_ids = ["7407592"]
    fired = []
    wm.window_geometry_updated.connect(lambda: fired.append(1))
    wm.refresh_geometry()
    assert wm.window_geometry == {"7407592": (961, 31, 958, 1008)}
    assert fired == [1]
