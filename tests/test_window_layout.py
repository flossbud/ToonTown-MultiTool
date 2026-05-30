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
