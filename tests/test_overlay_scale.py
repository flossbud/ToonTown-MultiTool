from utils.overlay.scale import clamp_scale, step_scale, SCALE_MIN, SCALE_MAX

def test_clamp_bounds():
    assert clamp_scale(0.1) == SCALE_MIN
    assert clamp_scale(9.0) == SCALE_MAX
    assert clamp_scale(1.2) == 1.2

def test_step_up_and_down():
    # one notch up from 1.0 is 1.08, then clamps within range
    assert round(step_scale(1.0, 1), 2) == 1.08
    assert round(step_scale(1.0, -1), 2) == 0.92

def test_snap_to_100_within_window():
    # landing within the snap window of 1.0 snaps exactly to 1.0
    assert step_scale(1.05, -1) == 1.0   # 1.05 - 0.08 = 0.97 -> within 0.04 of 1.0 -> snaps
    assert step_scale(0.96, 1) == 1.0    # 0.96 + 0.08 = 1.04 -> within 0.04 -> snaps

def test_no_snap_outside_window():
    assert step_scale(1.20, 1) != 1.0
