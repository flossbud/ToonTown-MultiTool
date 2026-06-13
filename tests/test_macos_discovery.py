"""Tests for utils.macos_discovery pure parsing layer."""

from __future__ import annotations

import pytest

import utils.macos_discovery as md
from utils.macos_discovery import GameWindow, identify_game_windows


@pytest.fixture(autouse=True)
def _reset_enum_cache():
    """Keep the module-level enumeration snapshot cache from leaking between
    tests (the real-_enumerate tests would otherwise pollute later ones)."""
    md._reset_enum_cache()
    yield
    md._reset_enum_cache()


def _w(pid, num, name, x=0, y=0, w=800, h=600):
    """Build a CGWindowListCopyWindowInfo-shaped dict."""
    return {
        "kCGWindowOwnerPID": pid,
        "kCGWindowNumber": num,
        "kCGWindowOwnerName": name,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }


def test_identifies_game_windows_and_excludes_others():
    info = [
        _w(101, 1, "Toontown Rewritten"),
        _w(102, 2, "Finder"),
        _w(103, 3, "Corporate Clash"),
    ]
    result = identify_game_windows(info)
    assert len(result) == 2
    assert [(r.pid, r.window_id, r.game) for r in result] == [
        (101, 1, "ttr"),
        (103, 3, "cc"),
    ]


def test_skips_zero_area_and_missing_fields():
    info = [
        _w(101, 1, "Toontown Rewritten", w=0, h=0),
        {
            "kCGWindowOwnerName": "Corporate Clash",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
        },
    ]
    assert identify_game_windows(info) == []


def test_startswith_semantics():
    info = [
        _w(101, 1, "Toontown Rewritten (Beta)"),
        _w(102, 2, "Not Toontown Rewritten"),
    ]
    result = identify_game_windows(info)
    assert len(result) == 1
    assert result[0].pid == 101
    assert result[0].game == "ttr"


def test_bounds_tuple_and_bundle_id_default():
    info = [_w(101, 1, "Toontown Rewritten", x=10, y=20, w=300, h=400)]
    result = identify_game_windows(info)
    assert len(result) == 1
    win = result[0]
    assert isinstance(win, GameWindow)
    assert win.bounds == (10, 20, 300, 400)
    assert win.bundle_id is None


def test_cc_prefix_and_beta_suffix_match():
    info = [
        _w(1, 1, "Corporate Clash"),
        _w(2, 2, "Corporate Clash (Test)"),
        _w(3, 3, "Not Corporate Clash"),
    ]
    recs = identify_game_windows(info)
    assert [(r.pid, r.game) for r in recs] == [(1, "cc"), (2, "cc")]


def test_malformed_record_skipped_not_aborting():
    # A bad record in the middle must not drop the good ones around it.
    good1 = _w(10, 11, "Toontown Rewritten")
    bad_owner = {"kCGWindowOwnerName": None, "kCGWindowOwnerPID": 1, "kCGWindowNumber": 2,
                 "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 8, "Height": 8}}
    bad_bounds = {"kCGWindowOwnerName": "Toontown Rewritten", "kCGWindowOwnerPID": 5,
                  "kCGWindowNumber": 6, "kCGWindowBounds": None}
    bad_dims = {"kCGWindowOwnerName": "Toontown Rewritten", "kCGWindowOwnerPID": 7,
                "kCGWindowNumber": 8, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": "x", "Height": 9}}
    bad_pid = {"kCGWindowOwnerName": "Toontown Rewritten", "kCGWindowOwnerPID": "nope",
               "kCGWindowNumber": 9, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 8, "Height": 8}}
    good2 = _w(20, 21, "Corporate Clash")
    recs = identify_game_windows([good1, bad_owner, bad_bounds, bad_dims, bad_pid, good2])
    assert [(r.pid, r.window_id) for r in recs] == [(10, 11), (20, 21)]


def test_individual_zero_or_negative_dimension_skipped():
    assert identify_game_windows([_w(1, 1, "Toontown Rewritten", w=10, h=0)]) == []
    assert identify_game_windows([_w(1, 1, "Toontown Rewritten", w=-5, h=10)]) == []


def _gw(pid, wid, game, owner, bounds=(0, 0, 800, 600), bundle_id=None):
    return GameWindow(
        pid=pid, window_id=wid, game=game, owner=owner, bounds=bounds, bundle_id=bundle_id
    )


def test_find_game_windows_pairs_ids_and_games(monkeypatch):
    recs = [
        _gw(101, 11, "ttr", "Toontown Rewritten"),
        _gw(103, 33, "cc", "Corporate Clash"),
    ]
    monkeypatch.setattr(md, "_enumerate_game_windows", lambda: recs)
    assert md.find_game_windows() == [("11", "ttr"), ("33", "cc")]


def test_get_window_root_x(monkeypatch):
    recs = [_gw(101, 11, "ttr", "Toontown Rewritten", bounds=(42, 0, 800, 600))]
    monkeypatch.setattr(md, "_enumerate_game_windows", lambda: recs)
    assert md.get_window_root_x("11") == 42
    assert md.get_window_root_x("999") is None


def test_geometry_pid_game_for_window(monkeypatch):
    recs = [_gw(101, 11, "ttr", "Toontown Rewritten", bounds=(42, 7, 800, 600))]
    monkeypatch.setattr(md, "_enumerate_game_windows", lambda: recs)
    assert md.get_window_geometry("11") == (42, 7, 800, 600)
    assert md.get_window_pid("11") == 101
    assert md.game_for_window_id("11") == "ttr"
    assert md.get_window_geometry("999") is None
    assert md.get_window_pid("999") is None
    assert md.game_for_window_id("999") is None


def test_toplevel_at_point_returns_none():
    assert md.toplevel_at_point(10, 20) is None


# ── Error contract: query functions never raise (match x11_discovery) ────────

def test_enumerate_returns_empty_on_quartz_error(monkeypatch):
    def _boom():
        raise RuntimeError("Quartz unavailable")

    monkeypatch.setattr(md, "_quartz", _boom)
    assert md._enumerate_game_windows() == []


def test_enumerate_is_cached_within_ttl(monkeypatch):
    """The expensive window-server enumeration is served from a snapshot cache on
    repeated calls within the TTL (the per-keystroke + N+1-per-poll fix), and a
    reset forces a fresh enumeration."""
    calls = {"n": 0}

    def _fake_uncached():
        calls["n"] += 1
        return [GameWindow(1, 1, "ttr", "Toontown Rewritten", (0, 0, 800, 600))]

    monkeypatch.setattr(md, "_enumerate_game_windows_uncached", _fake_uncached)
    r1 = md._enumerate_game_windows()
    r2 = md._enumerate_game_windows()
    assert calls["n"] == 1              # second call served from the cache
    assert r1 == r2
    md._reset_enum_cache()
    md._enumerate_game_windows()
    assert calls["n"] == 2              # reset forces a fresh enumeration


def test_concurrent_miss_older_started_does_not_clobber_newer(monkeypatch):
    """Race fix: a slow OLDER-started enumeration that finishes AFTER a newer one
    must not overwrite the newer snapshot or restart its TTL (serving stale data
    past the TTL). Deterministic via events: the older call is held in-flight
    while a newer call completes and publishes, then the older is released."""
    import threading

    md._reset_enum_cache()
    started_evt = threading.Event()   # set once the older enumeration is in-flight
    release_evt = threading.Event()   # release the older enumeration to finish
    calls = {"n": 0}
    OLD = [GameWindow(1, 1, "ttr", "old", (0, 0, 1, 1))]
    NEW = [GameWindow(2, 2, "ttr", "new", (0, 0, 1, 1))]

    def _fake_uncached():
        calls["n"] += 1
        if calls["n"] == 1:           # older: started first, blocks, finishes last
            started_evt.set()
            release_evt.wait(timeout=5)
            return OLD
        return NEW                    # newer: started later, finishes first

    monkeypatch.setattr(md, "_enumerate_game_windows_uncached", _fake_uncached)

    older = {}
    t = threading.Thread(
        target=lambda: older.setdefault("r", md._enumerate_game_windows()))
    t.start()
    assert started_evt.wait(timeout=5)         # older enumeration now in-flight
    newer = md._enumerate_game_windows()        # newer: started later, publishes NEW
    assert newer == NEW
    release_evt.set()                           # older finishes, attempts a stale write
    t.join(timeout=5)
    assert not t.is_alive()
    # The older snapshot must NOT have clobbered the newer one or reset the TTL.
    assert md._enumerate_game_windows() == NEW
    md._reset_enum_cache()


def test_geometry_queries_return_none_when_enumeration_empty(monkeypatch):
    monkeypatch.setattr(md, "_enumerate_game_windows", lambda: [])
    assert md.get_window_root_x("11") is None
    assert md.get_window_geometry("11") is None
    assert md.get_window_pid("11") is None
    assert md.game_for_window_id("11") is None
    assert md.find_game_windows() == []


def test_get_active_window_id_returns_none_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("window server gone")

    # Whether the AppKit import fails (CI/Linux) or _enumerate raises (macOS),
    # get_active_window_id must swallow it and return None, never propagate.
    monkeypatch.setattr(md, "_enumerate_game_windows", _boom)
    assert md.get_active_window_id() is None


def test_process_bundle_id_returns_none_on_error(monkeypatch):
    # Not importable on non-macOS, and AppKit can raise; must yield None.
    assert md.process_bundle_id(-1) is None
