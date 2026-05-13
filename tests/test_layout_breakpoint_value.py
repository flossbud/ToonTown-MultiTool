"""Pins H_FULL after the chip-rail redesign. The first cut used H_FULL=852
with CHIP_RAIL_H=52, but 52 was too small for chips to render text under
icon — Qt compressed the rail and clipped labels. CHIP_RAIL_H bumped to 64;
H_FULL bumped to 864 so the full-UI content budget at the breakpoint stays
at 744 px (864 − 56 header − 64 chip rail = 744), leaving _FullToonCard
reference rects untouched."""

from main import H_FULL, W_FULL


def test_h_full_is_864_for_chip_rail_chrome():
    assert H_FULL == 864


def test_w_full_unchanged_at_1280():
    assert W_FULL == 1280
