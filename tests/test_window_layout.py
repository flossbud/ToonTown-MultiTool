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
