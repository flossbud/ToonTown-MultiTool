from utils.window_layout import clamp_window_height


def test_clamp_uses_target_on_large_screen():
    assert clamp_window_height(available_height=1440) == 862


def test_clamp_shrinks_to_screen_minus_margin_on_small_screen():
    # 768 - 48 = 720, which is below the 862 target -> the smaller wins.
    assert clamp_window_height(available_height=768) == 720


def test_clamp_custom_target_and_margin():
    assert clamp_window_height(available_height=900, target=862, margin=48) == 852


def test_clamp_falls_back_to_target_when_available_unknown():
    assert clamp_window_height(available_height=0) == 862


def test_clamp_tiny_screen_never_negative():
    assert clamp_window_height(available_height=32) == 32


from utils.window_layout import compute_logo_size


def test_logo_size_fits_at_min_width():
    # logo asset is 2100x722 (aspect ~2.908). At header width 575, the 80px
    # target height yields ~233px width, under the 427px guard -> unchanged.
    w, h = compute_logo_size(header_width=575, asset_w=2100, asset_h=722, target_height=80)
    assert h == 80
    assert 230 <= w <= 236


def test_logo_size_scales_down_when_too_wide():
    # A very narrow header forces the logo to shrink below target height.
    w, h = compute_logo_size(header_width=200, asset_w=2100, asset_h=722, target_height=80)
    # max_logo_width = 200 - 2*74 = 52 -> height = round(52/2.908) = 18
    assert w == 52
    assert h == 18


def test_logo_size_hides_when_no_safe_space():
    assert compute_logo_size(header_width=100, asset_w=2100, asset_h=722) == (0, 0)


def test_logo_size_raises_on_bad_asset_dims():
    import pytest
    with pytest.raises(ValueError):
        compute_logo_size(header_width=575, asset_w=0, asset_h=722)


from utils.window_layout import position_inside

# A Windows 11 laptop at 1920x1200 and 150% has 1280x800 logical pixels, and
# 1280x752 usable above its taskbar. That is too small for the window, so the
# UI scale is 0.80, and Qt's coordinates are physical / (1.5 * 0.8): the
# usable area Qt reports is 1600x940. The window's default height there is
# clamp_window_height(940, target=860) = 860, at (100, 100).
LAPTOP_USABLE = (0, 0, 1600, 940)


def test_position_inside_lifts_the_default_window_off_the_laptop_taskbar():
    # 100 + 860 = 960 runs 20 px (16 logical) under the taskbar; it fits
    # once its top is at 80, and its left edge stays where it was.
    assert position_inside((100, 100, 880, 860), LAPTOP_USABLE) == (100, 80)


def test_position_inside_leaves_a_window_that_fits_alone():
    assert position_inside((100, 100, 880, 860), (0, 0, 1920, 1032)) == (100, 100)
    assert position_inside((100, 80, 880, 860), LAPTOP_USABLE) == (100, 80)


def test_position_inside_respects_a_taskbar_on_the_top_or_left():
    assert position_inside((100, 20, 880, 700), (0, 60, 1600, 940)) == (100, 60)
    assert position_inside((10, 100, 880, 700), (72, 0, 1528, 1000)) == (72, 100)


def test_position_inside_works_on_a_screen_away_from_the_origin():
    # A second monitor left of and above the primary one.
    area = (-1920, -1080, 1920, 1040)
    assert position_inside((-1500, -900, 880, 860), area) == (-1500, -900)
    assert position_inside((-1500, -100, 880, 860), area) == (-1500, -900)
    assert position_inside((-300, -900, 880, 860), area) == (-880, -900)


def test_position_inside_keeps_the_top_left_reachable_when_too_big():
    assert position_inside((100, 100, 880, 860), (0, 0, 800, 600)) == (0, 0)


def test_position_inside_without_a_usable_area_changes_nothing():
    assert position_inside((100, 100, 880, 860), (0, 0, 0, 0)) == (100, 100)
