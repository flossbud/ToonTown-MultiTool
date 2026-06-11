"""WindowManager geometry cache, with x11_discovery faked out."""
from services.window_manager import WindowManager
from utils import x11_discovery


def test_geometry_cache_refresh_and_get(monkeypatch):
    geoms = {"10": (0, 0, 1280, 720), "20": (1300, 0, 1920, 1080)}
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: geoms.get(wid), raising=False)
    wm = WindowManager()
    wm.ttr_window_ids = ["10", "20"]
    wm.refresh_geometry()
    assert wm.get_window_geometry("10") == (0, 0, 1280, 720)
    assert wm.get_window_geometry("20") == (1300, 0, 1920, 1080)


def test_geometry_change_emits_signal(monkeypatch):
    geoms = {"10": (0, 0, 1280, 720)}
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: geoms.get(wid), raising=False)
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
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: (5, 6, 700, 500), raising=False)
    wm = WindowManager()
    wm.ttr_window_ids = ["99"]
    # Not in cache: on-demand query, cached because tracked.
    assert wm.get_window_geometry("99") == (5, 6, 700, 500)
    assert wm.window_geometry["99"] == (5, 6, 700, 500)


def test_geometry_fallback_does_not_cache_untracked(monkeypatch):
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: (5, 6, 700, 500), raising=False)
    wm = WindowManager()
    # "99" is not tracked: live value returned but never cached.
    assert wm.get_window_geometry("99") == (5, 6, 700, 500)
    assert "99" not in wm.window_geometry


def test_geometry_removed_window_fires_signal_and_purges(monkeypatch):
    # Removal is the load-bearing trigger for the live mismatch PAUSE:
    # a member window disappearing must fire the change signal.
    geoms = {"10": (0, 0, 1280, 720), "20": (1300, 0, 1920, 1080)}
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: geoms.get(wid), raising=False)
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
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: geoms.get(wid), raising=False)
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

    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        query_and_disable, raising=False)
    wm.refresh_geometry()
    assert wm.window_geometry == {}


def test_geometry_unknown_window_none(monkeypatch):
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: None, raising=False)
    wm = WindowManager()
    assert wm.get_window_geometry("nope") is None
