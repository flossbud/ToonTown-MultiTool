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


def test_geometry_get_falls_back_to_live_query(monkeypatch):
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: (5, 6, 700, 500), raising=False)
    wm = WindowManager()
    # Not in cache: on-demand query.
    assert wm.get_window_geometry("99") == (5, 6, 700, 500)


def test_geometry_unknown_window_none(monkeypatch):
    monkeypatch.setattr(x11_discovery, "get_window_geometry",
                        lambda wid: None, raising=False)
    wm = WindowManager()
    assert wm.get_window_geometry("nope") is None
