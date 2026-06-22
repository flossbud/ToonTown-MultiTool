import math
from utils.radial_menu_layout import account_ring_angles, polar_point, MAIN_RING_ANGLES


def test_account_ring_angles_reserves_top_and_spaces_evenly():
    assert account_ring_angles(0) == []
    assert account_ring_angles(1) == [90.0]
    assert account_ring_angles(3) == [0.0, 90.0, 180.0]
    a8 = account_ring_angles(8)
    assert len(a8) == 8
    step = 360.0 / 9
    assert a8 == [-90.0 + step * k for k in range(1, 9)]
    assert all(round((ang - (-90.0)) % 360.0, 6) != 0.0 for ang in a8)


def test_polar_point_places_on_circle():
    x, y = polar_point(100.0, 100.0, 50.0, 0.0)
    assert round(x, 6) == 150.0 and round(y, 6) == 100.0
    x, y = polar_point(100.0, 100.0, 50.0, -90.0)
    assert round(x, 6) == 100.0 and round(y, 6) == 50.0


def test_main_ring_angles_match_locked_layout():
    assert MAIN_RING_ANGLES == {
        "accounts": -142.0, "home": -90.0, "settings": -38.0,
        "close": 138.0, "exit": 42.0,
    }


def test_windowed_ring_angles_match_locked_layout():
    from utils.radial_menu_layout import WINDOWED_RING_ANGLES
    assert WINDOWED_RING_ANGLES == {
        "accounts": -142.0, "transparent": -90.0, "close": 90.0,
    }
