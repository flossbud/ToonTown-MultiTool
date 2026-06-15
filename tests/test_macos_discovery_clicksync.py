"""Click-sync geometry + source-resolver helpers (no PyObjC)."""
import types
import utils.macos_discovery as disc


def _rec(wid, bounds):
    return types.SimpleNamespace(window_id=wid, bounds=bounds, pid=1, game="ttr")


def test_fresh_geometry_is_uncached(monkeypatch):
    box = [[_rec(100, (0, 30, 800, 600))]]
    monkeypatch.setattr(disc, "_enumerate_game_windows_uncached", lambda: box[0])
    assert disc.get_window_geometry_fresh("100") == (0, 30, 800, 600)
    assert disc.get_window_geometry_fresh("999") is None
    box[0] = [_rec(100, (10, 40, 810, 610))]            # a moved window
    assert disc.get_window_geometry_fresh("100") == (10, 40, 810, 610)  # reflected live


def test_active_source_window_member_inside():
    wid = disc.active_source_window(
        100, 100, ["55", "77"],
        active_fn=lambda: "77",
        geom_fn=lambda w: (50, 50, 200, 200))
    assert wid == "77"


def test_active_source_window_rejects_non_member():
    assert disc.active_source_window(
        100, 100, ["55"], active_fn=lambda: "77",
        geom_fn=lambda w: (0, 0, 999, 999)) is None


def test_active_source_window_rejects_point_outside():
    assert disc.active_source_window(
        500, 500, ["77"], active_fn=lambda: "77",
        geom_fn=lambda w: (0, 0, 100, 100)) is None


def test_active_source_window_none_active():
    assert disc.active_source_window(
        1, 1, ["77"], active_fn=lambda: None, geom_fn=lambda w: (0, 0, 9, 9)) is None
