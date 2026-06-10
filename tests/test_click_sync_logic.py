"""Pure-logic tests for click sync: no X, no Qt."""
from services.click_sync_logic import (
    ASPECT_TOLERANCE, aspect_compatible, map_point, compute_slot_states, Gesture,
)


def test_aspect_identical_sizes_compatible():
    assert aspect_compatible([(0, 0, 1280, 720), (0, 0, 1280, 720)])


def test_aspect_scaled_same_ratio_compatible():
    assert aspect_compatible([(0, 0, 1280, 720), (1300, 50, 1920, 1080)])


def test_aspect_different_ratio_incompatible():
    assert not aspect_compatible([(0, 0, 1280, 720), (0, 0, 1280, 1024)])


def test_aspect_all_pairs_not_just_first():
    # a~b and b~c within tolerance individually, a~c outside it: must be False.
    a, b, c = (0, 0, 1000, 1000), (0, 0, 1000, 991), (0, 0, 1000, 982)
    assert aspect_compatible([a, b]) and aspect_compatible([b, c])
    assert not aspect_compatible([a, b, c])


def test_aspect_zero_size_incompatible():
    assert not aspect_compatible([(0, 0, 1280, 720), (0, 0, 0, 0)])


def test_aspect_single_window_trivially_compatible():
    assert aspect_compatible([(0, 0, 1280, 720)])


def test_map_point_identity():
    src = (100, 200, 800, 600)
    tgt = (1000, 50, 800, 600)
    assert map_point(src, tgt, 100 + 400, 200 + 300) == (400, 300)


def test_map_point_scales():
    src = (0, 0, 1280, 720)
    tgt = (0, 0, 1920, 1080)
    assert map_point(src, tgt, 1280, 720) == (1920, 1080)
    assert map_point(src, tgt, 640, 360) == (960, 540)


def test_map_point_out_of_bounds_passes_through():
    # Release outside the source window maps to outside the target: NOT clamped.
    src = (100, 100, 800, 600)
    tgt = (0, 0, 800, 600)
    tx, ty = map_point(src, tgt, 50, 50)  # left/above the source
    assert tx < 0 and ty < 0


def test_states_all_off_when_no_members():
    assert compute_slot_states(set(), {}, True) == {0: "off", 1: "off", 2: "off", 3: "off"}


def test_states_single_member_armed():
    s = compute_slot_states({0}, {0: True}, True)
    assert s[0] == "armed" and s[1] == "off"


def test_states_two_usable_compatible_active():
    s = compute_slot_states({0, 1}, {0: True, 1: True}, True)
    assert s[0] == "active" and s[1] == "active"


def test_states_mismatch_marks_members_error():
    s = compute_slot_states({0, 1}, {0: True, 1: True}, False)
    assert s[0] == "error" and s[1] == "error"


def test_states_missing_window_pauses_group():
    # Slot 2 has no window: it shows error, usable members drop to armed
    # (group is all-or-nothing in v1), nothing is active.
    s = compute_slot_states({0, 1, 2}, {0: True, 1: True, 2: False}, True)
    assert s[2] == "error" and s[0] == "armed" and s[1] == "armed"
    assert "active" not in s.values()


def test_aspect_empty_list_trivially_compatible():
    assert aspect_compatible([])


def test_states_unusable_plus_mismatch_usable_show_error():
    # Slot 2 unusable AND the two usable members mismatched: mismatch wins
    # for the usable members (error, not armed); the unusable slot is error.
    s = compute_slot_states({0, 1, 2}, {0: True, 1: True, 2: False}, False)
    assert s[0] == "error" and s[1] == "error" and s[2] == "error"


def test_gesture_is_immutable():
    import dataclasses
    import pytest as _pytest
    g = Gesture(source_slot=0, source_geom=(0, 0, 1, 1), press_root=(0, 0),
                press_state=0, press_time=0, targets={})
    with _pytest.raises(dataclasses.FrozenInstanceError):
        g.source_slot = 1


def test_gesture_records_targets_and_press():
    g = Gesture(source_slot=0, source_geom=(0, 0, 100, 100), press_root=(10, 20),
                press_state=0, press_time=1234,
                targets={1: ("555", (200, 0, 200, 200), (20, 40))})
    assert g.source_slot == 0
    assert g.targets[1][0] == "555"
    assert g.targets[1][2] == (20, 40)  # press position mapped into the target
