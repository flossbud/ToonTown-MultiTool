"""Tests for the pure 2x2 cell-assignment helper (position-based card placement).

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_window_cell_assignment.py -q
"""
from __future__ import annotations

from utils.window_cell_assignment import assign_window_cells, occupied_cells


# Cells: 0=TL, 1=TR, 2=BL, 3=BR.

def test_empty_returns_empty():
    assert assign_window_cells([]) == []


def test_single_window_takes_top_left():
    assert assign_window_cells([(100, 100)]) == [0]


def test_full_2x2_in_reading_order():
    # input already TL, TR, BL, BR
    centers = [(0, 0), (100, 0), (0, 100), (100, 100)]
    assert assign_window_cells(centers) == [0, 1, 2, 3]


def test_full_2x2_scrambled_input_maps_each_to_its_quadrant():
    # input order BL, TL, BR, TR
    centers = [(0, 100), (0, 0), (100, 100), (100, 0)]
    assert assign_window_cells(centers) == [2, 0, 3, 1]


def test_side_by_side_pair_fills_top_row():
    centers = [(0, 0), (100, 0)]  # left, right, same y
    assert assign_window_cells(centers) == [0, 1]


def test_vertical_stack_fills_left_column():
    centers = [(0, 0), (0, 100)]  # top, bottom, same x
    assert assign_window_cells(centers) == [0, 2]


def test_two_top_one_bottom_left():
    centers = [(0, 0), (100, 0), (0, 100)]  # TL, TR, B-left
    assert assign_window_cells(centers) == [0, 1, 2]


def test_l_shape_missing_top_right():
    centers = [(0, 0), (0, 100), (100, 100)]  # TL, BL, BR
    assert assign_window_cells(centers) == [0, 2, 3]


def test_l_shape_missing_bottom_left():
    centers = [(0, 0), (100, 0), (100, 100)]  # TL, TR, BR
    assert assign_window_cells(centers) == [0, 1, 3]


def test_more_than_four_windows_extras_get_negative_one():
    centers = [(0, 0), (100, 0), (0, 100), (100, 100), (50, 50)]
    cells = assign_window_cells(centers)
    assert sorted(c for c in cells if c >= 0) == [0, 1, 2, 3]
    assert cells.count(-1) == 1


def test_result_is_deterministic_on_exact_ties():
    # Four coincident points: every cell is equidistant; the top-left-first
    # tie-break must still produce a stable, distinct-cell assignment.
    centers = [(50, 50)] * 4
    assert assign_window_cells(centers) == [0, 1, 2, 3]


def test_occupied_cells_identity_partial():
    # 2 windows, identity routing -> top row cells {0,1}
    assert occupied_cells([0, 1, 2, 3], 2) == frozenset({0, 1})


def test_occupied_cells_permuted_vertical_stack():
    # 2 windows, slot 1 routed to cell 2 (vertical stack) -> {0,2}
    assert occupied_cells([0, 2, 1, 3], 2) == frozenset({0, 2})


def test_occupied_cells_empty_and_full():
    assert occupied_cells([0, 1, 2, 3], 0) == frozenset()
    assert occupied_cells([0, 1, 2, 3], 4) == frozenset({0, 1, 2, 3})
    # defensive: an empty routing with a positive count yields no cells
    assert occupied_cells([], 3) == frozenset()


def test_occupied_cells_clamps_and_floors_count():
    # count larger than 4 clamps to the routing length; negative floors to 0
    assert occupied_cells([0, 1, 2, 3], 9) == frozenset({0, 1, 2, 3})
    assert occupied_cells([0, 1, 2, 3], -1) == frozenset()


def test_occupied_cells_short_routing():
    # defensive: a short routing list never indexes past its length
    assert occupied_cells([2, 0], 5) == frozenset({2, 0})
