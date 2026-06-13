"""Tests for utils.macos_discovery pure parsing layer."""

from __future__ import annotations

from utils.macos_discovery import GameWindow, identify_game_windows


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
