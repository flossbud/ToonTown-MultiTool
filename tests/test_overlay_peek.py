# tests/test_overlay_peek.py
from utils.overlay.peek import peeking_indices, GhostPointStore


def test_peeking_indices_point_inside_rect():
    rects = [(0, 0, 100, 100), (200, 0, 100, 100)]
    assert peeking_indices([(50, 50)], rects) == {0}
    assert peeking_indices([(250, 50)], rects) == {1}


def test_peeking_indices_multiple_points_multiple_cards():
    rects = [(0, 0, 100, 100), (200, 0, 100, 100)]
    assert peeking_indices([(10, 10), (210, 10)], rects) == {0, 1}


def test_peeking_indices_edge_is_inside_and_outside_is_excluded():
    rects = [(0, 0, 100, 100)]
    assert peeking_indices([(0, 0)], rects) == {0}          # top-left corner inside
    assert peeking_indices([(100, 100)], rects) == set()    # bottom-right is exclusive
    assert peeking_indices([(150, 150)], rects) == set()


def test_peeking_indices_empty_inputs():
    assert peeking_indices([], [(0, 0, 10, 10)]) == set()
    assert peeking_indices([(1, 1)], []) == set()


def test_ghost_store_motion_and_points():
    s = GhostPointStore()
    s.ingest(("motion", [(0, 10, 20), (2, 30, 40)]))
    assert sorted(s.points()) == [(10, 20), (30, 40)]


def test_ghost_store_motion_updates_same_slot():
    s = GhostPointStore()
    s.ingest(("motion", [(1, 5, 5)]))
    s.ingest(("motion", [(1, 9, 9)]))
    assert s.points() == [(9, 9)]


def test_ghost_store_release_and_clear():
    s = GhostPointStore()
    s.ingest(("motion", [(0, 1, 1), (1, 2, 2)]))
    s.ingest(("release", [(0, 1, 1)]))
    assert s.points() == [(2, 2)]
    s.clear()
    assert s.points() == []


def test_ghost_store_ignores_unknown_kind():
    s = GhostPointStore()
    s.ingest(("nonsense", [(0, 1, 1)]))
    assert s.points() == []


def test_ghost_store_ignores_press_kind():
    # The service also emits a "press" kind; peek tracks positions only, so it
    # must be ignored (and never leak a tracked point).
    s = GhostPointStore()
    s.ingest(("press", [(0, 1, 1)]))
    assert s.points() == []


def test_ghost_store_ignores_malformed_payload():
    s = GhostPointStore()
    s.ingest(None)
    s.ingest(("motion",))            # 1-tuple: kind/items unpack fails
    assert s.points() == []


def test_control_hits_point_on_control_returns_local_coords():
    from utils.overlay.peek import control_hits
    # card 0 surface at (100,100) size 200x200; one control rect at card-local
    # (10,10,20,20). Scale 1.0. A global point at (115,115) -> local (15,15),
    # inside the control.
    cards = [(0, (100, 100, 200, 200), [(10, 10, 20, 20)])]
    assert control_hits([(115, 115)], cards, 1.0) == [(0, 15, 15)]


def test_control_hits_body_point_is_no_hit():
    from utils.overlay.peek import control_hits
    cards = [(0, (100, 100, 200, 200), [(10, 10, 20, 20)])]
    # local (50,50) is in the card but not on the control.
    assert control_hits([(150, 150)], cards, 1.0) == []


def test_control_hits_divides_by_scale():
    from utils.overlay.peek import control_hits
    # Surface twice as big on screen (scale 2.0); a global point at (140,140)
    # -> local ((140-100)/2,(140-100)/2) == (20,20), inside (10,10,20,20).
    cards = [(0, (100, 100, 400, 400), [(10, 10, 20, 20)])]
    assert control_hits([(140, 140)], cards, 2.0) == [(0, 20, 20)]


def test_control_hits_picks_containing_card_only():
    from utils.overlay.peek import control_hits
    cards = [
        (0, (0, 0, 100, 100), [(0, 0, 100, 100)]),
        (1, (200, 0, 100, 100), [(0, 0, 100, 100)]),
    ]
    # Point only in card 1.
    assert control_hits([(250, 50)], cards, 1.0) == [(1, 50, 50)]


def test_control_hits_zero_scale_falls_back_to_one():
    from utils.overlay.peek import control_hits
    cards = [(0, (0, 0, 100, 100), [(0, 0, 100, 100)])]
    assert control_hits([(20, 20)], cards, 0.0) == [(0, 20, 20)]
